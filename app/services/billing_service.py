"""
Premium subscription service (€10/month, Stripe Billing).

Flow:
  1. start_checkout()  → Stripe-hosted Checkout page (card details never touch us)
  2. Stripe redirects back; sync() reads the session and activates Premium at once
  3. Webhooks (customer.subscription.*) keep the state current on renewals,
     failed payments and cancellations
  4. get_status() re-reads Stripe when the paid period has lapsed, so Premium
     still expires correctly if a webhook was missed

Cancelling keeps Premium until the end of the paid month (cancel_at_period_end).
"""
import logging
import uuid
from datetime import datetime

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import stripe_client
from app.models.subscription import Subscription
from app.models.user import User

logger = logging.getLogger(__name__)

# Stripe statuses that keep Premium on. past_due stays on while Stripe retries the card.
ACTIVE_STATUSES = {"active", "trialing", "past_due"}


def _require_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments are not available right now.")


def _frontend_base(origin: str | None) -> str:
    """Where Stripe sends the user back. Only origins we already trust for CORS."""
    origin = (origin or "").rstrip("/")
    if origin and origin in [o.rstrip("/") for o in settings.allowed_origins_list]:
        return origin
    return settings.FRONTEND_URL.rstrip("/")


def _record(db: Session, user: User) -> Subscription:
    record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not record:
        record = Subscription(user_id=user.id)
        db.add(record)
        db.flush()
    return record


def _apply(db: Session, user: User, record: Subscription, sub) -> None:
    """Copy a Stripe subscription onto our record and the user's Premium flag."""
    period_end = sub.get("current_period_end")
    if not period_end:  # newer Stripe API versions report it per item
        items = (sub.get("items") or {}).get("data") or []
        period_end = items[0].get("current_period_end") if items else None

    record.stripe_subscription_id = sub["id"]
    record.stripe_customer_id = sub.get("customer") or record.stripe_customer_id
    record.status = sub.get("status")
    record.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    record.current_period_end = datetime.utcfromtimestamp(period_end) if period_end else None
    user.is_premium = record.status in ACTIVE_STATUSES
    db.commit()


def _refresh(db: Session, user: User, record: Subscription) -> None:
    if record.stripe_subscription_id:
        _apply(db, user, record, stripe_client.get_subscription(record.stripe_subscription_id))


def _serialize(user: User, record: Subscription | None) -> dict:
    return {
        "is_premium": bool(user.is_premium),
        "status": record.status if record else None,
        "current_period_end": record.current_period_end if record else None,
        "cancel_at_period_end": bool(record.cancel_at_period_end) if record else False,
        "price_eur": settings.PREMIUM_PRICE_EUR,
    }


# ── Buyer actions ─────────────────────────────────────────────────────────────

def start_checkout(db: Session, user: User, origin: str | None) -> dict:
    _require_stripe()
    record = _record(db, user)
    if user.is_premium and record.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="You already have Premium.")

    try:
        if not record.stripe_customer_id:
            record.stripe_customer_id = stripe_client.create_customer(user.email, user.full_name, str(user.id))
            db.commit()
        base = _frontend_base(origin)
        url = stripe_client.create_premium_checkout(
            customer_id=record.stripe_customer_id,
            user_id=str(user.id),
            success_url=f"{base}/profile?premium=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/pricing?premium=cancelled",
        )
    except stripe.error.StripeError as e:
        logger.warning("Premium checkout failed for %s: %s", user.id, e)
        raise HTTPException(status_code=502, detail="Could not start the checkout. Please try again.")
    return {"checkout_url": url}


def sync(db: Session, user: User, session_id: str | None = None) -> dict:
    """Pull the latest subscription state from Stripe (called on return from Checkout)."""
    _require_stripe()
    record = _record(db, user)
    try:
        if session_id:
            session = stripe_client.get_checkout_session(session_id)
            if session.get("client_reference_id") != str(user.id):
                raise HTTPException(status_code=403, detail="This checkout belongs to another account.")
            if session.get("subscription"):
                _apply(db, user, record, stripe_client.get_subscription(session["subscription"]))
        else:
            _refresh(db, user, record)
    except stripe.error.StripeError as e:
        logger.warning("Premium sync failed for %s: %s", user.id, e)
        raise HTTPException(status_code=502, detail="Could not confirm your subscription yet. Please refresh in a moment.")
    db.commit()
    return _serialize(user, record)


def get_status(db: Session, user: User) -> dict:
    record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    lapsed = bool(
        record and record.stripe_subscription_id and record.current_period_end
        and record.current_period_end < datetime.utcnow() and record.status in ACTIVE_STATUSES
    )
    if lapsed and settings.STRIPE_SECRET_KEY:
        try:
            _refresh(db, user, record)
        except stripe.error.StripeError as e:
            logger.warning("Premium refresh failed for %s: %s", user.id, e)
    return _serialize(user, record)


def set_cancel(db: Session, user: User, cancel: bool) -> dict:
    """Cancel at the end of the paid month (cancel=True) or undo that (cancel=False)."""
    _require_stripe()
    record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not record or not record.stripe_subscription_id or record.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="You don't have an active Premium subscription.")
    try:
        _apply(db, user, record, stripe_client.set_subscription_cancel(record.stripe_subscription_id, cancel))
    except stripe.error.StripeError as e:
        logger.warning("Premium cancel=%s failed for %s: %s", cancel, user.id, e)
        raise HTTPException(status_code=502, detail="Could not update your subscription. Please try again.")
    return _serialize(user, record)


def open_portal(db: Session, user: User, origin: str | None) -> dict:
    """Stripe-hosted page to change the card and download invoices."""
    _require_stripe()
    record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not record or not record.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account yet.")
    try:
        url = stripe_client.create_billing_portal(record.stripe_customer_id, f"{_frontend_base(origin)}/profile")
    except stripe.error.StripeError as e:
        logger.warning("Billing portal failed for %s: %s", user.id, e)
        raise HTTPException(status_code=502, detail="The billing page is not available right now.")
    return {"portal_url": url}


def cancel_now_for_deleted_user(db: Session, user: User) -> None:
    """Account deletion: stop billing immediately. Best-effort, never raises."""
    record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    user.is_premium = False
    if not record or not record.stripe_subscription_id or record.status == "canceled":
        return
    try:
        _apply(db, user, record, stripe_client.cancel_subscription(record.stripe_subscription_id))
    except Exception as e:
        logger.error("Could not cancel subscription %s of deleted user %s: %s", record.stripe_subscription_id, user.id, e)


# ── Webhook ───────────────────────────────────────────────────────────────────

def handle_subscription_event(db: Session, stripe_subscription_id: str, user_id: str | None = None) -> None:
    """
    A subscription changed on Stripe's side (renewal, failed payment, cancel).
    Re-reads it from the API rather than trusting the event payload's shape.
    """
    record = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
    sub = stripe_client.get_subscription(stripe_subscription_id)
    if not record:
        user_id = user_id or (sub.get("metadata") or {}).get("user_id")
        try:
            user_uuid = uuid.UUID(str(user_id)) if user_id else None
        except ValueError:
            user_uuid = None
        if user_uuid:
            record = db.query(Subscription).filter(Subscription.user_id == user_uuid).first()
        if not record and sub.get("customer"):
            record = db.query(Subscription).filter(Subscription.stripe_customer_id == sub["customer"]).first()
    if not record:
        logger.warning("Subscription event for unknown subscription %s", stripe_subscription_id)
        return
    # A stale event about an old subscription must not downgrade a user who has a newer one.
    if record.stripe_subscription_id and record.stripe_subscription_id != sub["id"] and sub.get("status") not in ACTIVE_STATUSES:
        return
    user = db.query(User).filter(User.id == record.user_id).first()
    if user:
        _apply(db, user, record, sub)
