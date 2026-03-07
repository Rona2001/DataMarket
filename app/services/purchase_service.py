"""
Purchase service — full escrow lifecycle.

States:
  PENDING    → buyer initiated payment, Stripe holds funds
  VERIFYING  → payment confirmed, running post-purchase dataset check
  COMPLETED  → funds released to seller, buyer can download
  DISPUTED   → buyer raised issue, funds frozen
  REFUNDED   → buyer refunded, seller not paid
  CANCELLED  → abandoned before payment

Key rules:
  - Free datasets skip Stripe entirely
  - Sellers must complete Stripe onboarding before receiving payments
  - Download access expires after SIGNED_URL_EXPIRY_SECONDS (default 1h)
  - Buyers can only dispute within 48h of purchase
"""
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.purchase import Purchase, PurchaseStatus
from app.models.dataset import Dataset, DatasetStatus
from app.models.user import User
from app.core import stripe_client, storage
from app.core.config import settings


DISPUTE_WINDOW_HOURS = 48
PLATFORM_FEE_RATE = 0.10


# ── Initiate purchase ─────────────────────────────────────────────────────────

def initiate_purchase(db: Session, buyer: User, dataset_id: str) -> dict:
    """
    Step 1 of the escrow flow.
    - Validates dataset is published and buyer hasn't already bought it
    - Creates a Purchase record (PENDING)
    - For paid datasets: creates Stripe PaymentIntent, returns client_secret
    - For free datasets: immediately completes the purchase
    """
    dataset = _get_purchasable_dataset(db, dataset_id)
    _check_not_already_purchased(db, buyer, dataset)
    _check_not_own_dataset(buyer, dataset)

    fee = round(dataset.price * PLATFORM_FEE_RATE, 2)
    payout = round(dataset.price - fee, 2)

    purchase = Purchase(
        id=str(uuid.uuid4()),
        buyer_id=buyer.id,
        dataset_id=dataset.id,
        amount=dataset.price,
        platform_fee=fee,
        seller_payout=payout,
        status=PurchaseStatus.PENDING,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)

    # Free dataset — skip Stripe, complete immediately
    if dataset.is_free:
        return _complete_free_purchase(db, purchase, dataset)

    # Paid dataset — need seller's Stripe account
    seller = db.query(User).filter(User.id == dataset.seller_id).first()
    if not seller.stripe_customer_id:
        raise HTTPException(
            status_code=402,
            detail="Seller has not completed payment onboarding. Cannot process payment.",
        )

    intent = stripe_client.create_payment_intent(
        amount_eur=dataset.price,
        buyer_email=buyer.email,
        dataset_id=str(dataset.id),
        dataset_title=dataset.title,
        seller_stripe_account_id=seller.stripe_customer_id,
    )

    purchase.stripe_payment_intent_id = intent["payment_intent_id"]
    db.commit()

    return {
        "purchase_id": str(purchase.id),
        "client_secret": intent["client_secret"],
        "amount_eur": dataset.price,
        "platform_fee_eur": fee,
        "seller_payout_eur": payout,
        "dataset_title": dataset.title,
    }


# ── Confirm payment (called by Stripe webhook) ────────────────────────────────

def confirm_payment(db: Session, payment_intent_id: str) -> Purchase:
    """
    Called when Stripe fires payment_intent.succeeded webhook.
    Moves purchase to COMPLETED and grants download access.
    """
    purchase = (
        db.query(Purchase)
        .filter(Purchase.stripe_payment_intent_id == payment_intent_id)
        .first()
    )
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found for this payment")

    if purchase.status != PurchaseStatus.PENDING:
        return purchase  # already processed (webhook retry)

    _complete_purchase(db, purchase)
    return purchase


# ── Download access (signed URL) ──────────────────────────────────────────────

def get_download_url(db: Session, purchase_id: str, buyer: User) -> dict:
    """
    Generate a fresh signed URL for a completed purchase.
    Each call generates a NEW signed URL — the old one may have expired.
    """
    purchase = _get_owned_purchase(db, purchase_id, buyer)

    if purchase.status != PurchaseStatus.COMPLETED:
        raise HTTPException(
            status_code=403,
            detail=f"Download not available. Purchase status: {purchase.status}",
        )

    dataset = db.query(Dataset).filter(Dataset.id == purchase.dataset_id).first()

    signed_url = storage.generate_signed_url(
        settings.SUPABASE_STORAGE_BUCKET,
        dataset.storage_key,
        expires_in=settings.SIGNED_URL_EXPIRY_SECONDS,
    )

    # Update access expiry in DB for audit trail
    purchase.access_expires_at = datetime.utcnow() + timedelta(
        seconds=settings.SIGNED_URL_EXPIRY_SECONDS
    )
    dataset.download_count += 1
    db.commit()

    return {
        "signed_url": signed_url,
        "expires_in_seconds": settings.SIGNED_URL_EXPIRY_SECONDS,
        "checksum": dataset.checksum,
        "dataset_title": dataset.title,
    }


# ── Dispute ───────────────────────────────────────────────────────────────────

def open_dispute(db: Session, purchase_id: str, buyer: User, reason: str) -> Purchase:
    """Buyer opens a dispute — funds frozen until resolved by admin."""
    purchase = _get_owned_purchase(db, purchase_id, buyer)

    if purchase.status != PurchaseStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only dispute completed purchases")

    hours_since = (datetime.utcnow() - purchase.completed_at).total_seconds() / 3600
    if hours_since > DISPUTE_WINDOW_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"Dispute window closed. Disputes must be opened within {DISPUTE_WINDOW_HOURS}h of purchase.",
        )

    purchase.status = PurchaseStatus.DISPUTED
    purchase.dispute_reason = reason
    purchase.dispute_opened_at = datetime.utcnow()
    db.commit()
    db.refresh(purchase)
    return purchase


def resolve_dispute(
    db: Session,
    purchase_id: str,
    admin: User,
    favour_buyer: bool,
) -> Purchase:
    """Admin resolves a dispute — either refund buyer or complete to seller."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase or purchase.status != PurchaseStatus.DISPUTED:
        raise HTTPException(status_code=404, detail="Active dispute not found")

    if favour_buyer:
        # Refund
        if purchase.stripe_payment_intent_id:
            stripe_client.refund_payment(
                purchase.stripe_payment_intent_id,
                reason="fraudulent",
            )
        purchase.status = PurchaseStatus.REFUNDED
    else:
        # Seller wins — mark completed
        purchase.status = PurchaseStatus.COMPLETED

    purchase.dispute_resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(purchase)
    return purchase


# ── Review ────────────────────────────────────────────────────────────────────

def leave_review(
    db: Session,
    purchase_id: str,
    buyer: User,
    rating: float,
    review: str = None,
) -> Purchase:
    if not 1.0 <= rating <= 5.0:
        raise HTTPException(status_code=422, detail="Rating must be between 1 and 5")

    purchase = _get_owned_purchase(db, purchase_id, buyer)

    if purchase.status != PurchaseStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only review completed purchases")
    if purchase.rating is not None:
        raise HTTPException(status_code=400, detail="You have already reviewed this purchase")

    purchase.rating = rating
    purchase.review = review

    # Recalculate dataset average rating
    dataset = db.query(Dataset).filter(Dataset.id == purchase.dataset_id).first()
    all_ratings = (
        db.query(Purchase.rating)
        .filter(
            Purchase.dataset_id == dataset.id,
            Purchase.rating.isnot(None),
        )
        .all()
    )
    ratings = [r[0] for r in all_ratings]
    dataset.average_rating = round(sum(ratings) / len(ratings), 2)

    db.commit()
    db.refresh(purchase)
    return purchase


# ── Seller onboarding ─────────────────────────────────────────────────────────

def onboard_seller(db: Session, seller: User, return_url: str, refresh_url: str) -> str:
    """
    Create a Stripe Express account for the seller (if not already done)
    and return the hosted onboarding URL.
    """
    if not seller.stripe_customer_id:
        account_id = stripe_client.create_seller_account(seller.email)
        seller.stripe_customer_id = account_id
        db.commit()

    onboarding_url = stripe_client.create_seller_onboarding_link(
        stripe_account_id=seller.stripe_customer_id,
        return_url=return_url,
        refresh_url=refresh_url,
    )
    return onboarding_url


def get_seller_payout_status(db: Session, seller: User) -> dict:
    """Check if seller's Stripe account is ready to receive payouts."""
    if not seller.stripe_customer_id:
        return {"onboarded": False, "charges_enabled": False, "payouts_enabled": False}

    return stripe_client.get_seller_account(seller.stripe_customer_id)


# ── Buyer purchase history ────────────────────────────────────────────────────

def get_buyer_purchases(db: Session, buyer: User) -> list:
    return (
        db.query(Purchase)
        .filter(Purchase.buyer_id == buyer.id)
        .order_by(Purchase.created_at.desc())
        .all()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_purchasable_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if dataset.status != DatasetStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Dataset is not available for purchase")
    return dataset


def _check_not_already_purchased(db: Session, buyer: User, dataset: Dataset) -> None:
    existing = db.query(Purchase).filter(
        Purchase.buyer_id == buyer.id,
        Purchase.dataset_id == dataset.id,
        Purchase.status.in_([PurchaseStatus.COMPLETED, PurchaseStatus.PENDING]),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already purchased this dataset")


def _check_not_own_dataset(buyer: User, dataset: Dataset) -> None:
    if str(buyer.id) == str(dataset.seller_id):
        raise HTTPException(status_code=400, detail="You cannot purchase your own dataset")


def _complete_purchase(db: Session, purchase: Purchase) -> None:
    purchase.status = PurchaseStatus.COMPLETED
    purchase.completed_at = datetime.utcnow()
    purchase.access_expires_at = datetime.utcnow() + timedelta(days=365)
    db.commit()


def _complete_free_purchase(db: Session, purchase: Purchase, dataset: Dataset) -> dict:
    _complete_purchase(db, purchase)
    signed_url = storage.generate_signed_url(
        settings.SUPABASE_STORAGE_BUCKET,
        dataset.storage_key,
    )
    dataset.download_count += 1
    db.commit()
    return {
        "purchase_id": str(purchase.id),
        "client_secret": None,
        "signed_url": signed_url,
        "expires_in_seconds": settings.SIGNED_URL_EXPIRY_SECONDS,
        "dataset_title": dataset.title,
        "is_free": True,
    }


def _get_owned_purchase(db: Session, purchase_id: str, buyer: User) -> Purchase:
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found")
    if str(purchase.buyer_id) != str(buyer.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return purchase
