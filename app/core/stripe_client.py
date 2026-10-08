"""
Stripe client — all Stripe API calls go through here.

Escrow model on DataMarket:
  1. Buyer pays → PaymentIntent captured (funds held by Stripe)
  2. Dataset verified + delivered → Transfer to seller's Stripe account
  3. Platform keeps 10% commission automatically via application_fee_amount
  4. Dispute? → Refund the PaymentIntent, cancel the transfer

Requires Stripe Connect (Express accounts) so sellers can receive payouts.
"""
import stripe
from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

PLATFORM_FEE_RATE = 0.10   # 10% commission


# ── Payment Intent (buyer pays) ───────────────────────────────────────────────

def create_payment_intent(
    amount_eur: float,
    buyer_email: str,
    dataset_id: str,
    dataset_title: str,
    seller_stripe_account_id: str,
) -> dict:
    """
    Create a PaymentIntent with:
    - application_fee_amount = 10% kept by platform
    - transfer_data → remaining 90% goes to seller's Stripe account
    - capture_method = automatic (funds held until confirmed)

    Returns the client_secret needed by the frontend to complete payment.
    """
    amount_cents = int(round(amount_eur * 100))
    fee_cents = int(round(amount_cents * PLATFORM_FEE_RATE))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="eur",
        # Card-only keeps the checkout form compact — no Link, wallets, or
        # "save card" prompt. (Still makes the PaymentElement render.)
        payment_method_types=["card"],
        application_fee_amount=fee_cents,
        transfer_data={"destination": seller_stripe_account_id},
        receipt_email=buyer_email,
        metadata={
            "dataset_id": dataset_id,
            "dataset_title": dataset_title,
        },
        description=f"datrust — {dataset_title}",
    )

    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
        "amount_eur": amount_eur,
        "fee_eur": round(fee_cents / 100, 2),
        "seller_payout_eur": round((amount_cents - fee_cents) / 100, 2),
        "status": intent.status,
    }


# ── Refunds (dispute resolution) ─────────────────────────────────────────────

def refund_payment(payment_intent_id: str, reason: str = "requested_by_customer") -> dict:
    """
    Refund a payment. Used when:
    - Dataset fails post-purchase verification
    - Buyer wins a dispute
    - Seller deletes a purchased dataset
    """
    refund = stripe.Refund.create(
        payment_intent=payment_intent_id,
        reason=reason,
    )
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "amount_refunded_eur": round(refund.amount / 100, 2),
    }


# ── Stripe Connect (seller onboarding) ───────────────────────────────────────

def create_seller_account(email: str) -> str:
    """
    Create a Stripe Express account for a new seller.
    Returns the Stripe account ID to store in the User record.
    """
    account = stripe.Account.create(
        type="express",
        country="FR",
        email=email,
        capabilities={
            "transfers": {"requested": True},
            "card_payments": {"requested": True},
        },
        business_type="individual",
        # Weekly payouts require an anchor day; Stripe rejects "weekly" without it.
        settings={"payouts": {"schedule": {"interval": "weekly", "weekly_anchor": "monday"}}},
    )
    return account.id


def create_seller_onboarding_link(stripe_account_id: str, return_url: str, refresh_url: str) -> str:
    """
    Generate a Stripe-hosted onboarding URL.
    Seller completes KYC/bank details on Stripe's side (we never touch that data).
    """
    link = stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


def get_seller_account(stripe_account_id: str) -> dict:
    """Check if a seller has completed Stripe onboarding."""
    account = stripe.Account.retrieve(stripe_account_id)
    capabilities = account.get("capabilities", {}) or {}
    return {
        "id": account.id,
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
        # Destination charges require the transfers capability to be "active".
        "transfers_active": capabilities.get("transfers") == "active",
    }


# ── Webhooks ──────────────────────────────────────────────────────────────────

def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify and parse an incoming Stripe webhook."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )


# ── Premium subscription (Stripe Billing) ─────────────────────────────────────

def create_customer(email: str, name: str | None, user_id: str) -> str:
    customer = stripe.Customer.create(email=email, name=name or None, metadata={"user_id": user_id})
    return customer.id


def create_premium_checkout(customer_id: str, user_id: str, success_url: str, cancel_url: str) -> str:
    """
    Stripe-hosted Checkout for the monthly Premium plan. Uses the configured
    Price when STRIPE_PREMIUM_PRICE_ID is set, otherwise an inline €/month price
    so the plan works without any dashboard setup.
    """
    if settings.STRIPE_PREMIUM_PRICE_ID:
        line_item = {"price": settings.STRIPE_PREMIUM_PRICE_ID, "quantity": 1}
    else:
        line_item = {
            "quantity": 1,
            "price_data": {
                "currency": "eur",
                "unit_amount": int(round(settings.PREMIUM_PRICE_EUR * 100)),
                "recurring": {"interval": "month"},
                "product_data": {"name": "datrust Premium"},
            },
        }
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[line_item],
        client_reference_id=user_id,
        metadata={"user_id": user_id},
        subscription_data={"metadata": {"user_id": user_id}},
        allow_promotion_codes=True,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


def get_checkout_session(session_id: str):
    return stripe.checkout.Session.retrieve(session_id)


def get_subscription(subscription_id: str):
    return stripe.Subscription.retrieve(subscription_id)


def set_subscription_cancel(subscription_id: str, cancel: bool):
    """Cancel at the end of the paid period (or undo it). Access continues until then."""
    return stripe.Subscription.modify(subscription_id, cancel_at_period_end=cancel)


def cancel_subscription(subscription_id: str):
    """Cancel immediately (account deletion)."""
    return stripe.Subscription.cancel(subscription_id)


def create_billing_portal(customer_id: str, return_url: str) -> str:
    return stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url).url
