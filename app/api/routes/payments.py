"""
Purchase routes:

Buyer:
  POST /purchases                       — initiate purchase (get client_secret)
  GET  /purchases                       — my purchase history
  GET  /purchases/{id}/download         — get signed download URL
  POST /purchases/{id}/dispute          — open a dispute
  POST /purchases/{id}/review           — leave a review

Seller:
  GET  /seller/onboarding               — get Stripe onboarding URL
  GET  /seller/payout-status            — check if ready to receive payments

Admin:
  POST /admin/purchases/{id}/resolve    — resolve dispute (favour buyer/seller)

Stripe:
  POST /webhooks/stripe                 — Stripe webhook handler
"""
from fastapi import APIRouter, Depends, Request, Header, HTTPException
from sqlalchemy.orm import Session
from typing import List
import stripe

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller, get_current_admin
from app.core import stripe_client
from app.schemas.purchase import (
    PurchaseInitiate, PurchasePublic,
    PaymentIntentResponse, DownloadResponse,
    DisputeRequest, ReviewRequest,
)
from app.services import purchase_service

router = APIRouter(tags=["Purchases & Payments"])


# ── Buyer — initiate purchase ─────────────────────────────────────────────────

@router.post("/purchases", response_model=PaymentIntentResponse, status_code=201)
def initiate_purchase(
    body: PurchaseInitiate,
    buyer=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start a purchase. Returns a Stripe client_secret for the frontend
    to call stripe.confirmPayment(). Free datasets complete instantly.
    """
    result = purchase_service.initiate_purchase(db, buyer, body.dataset_id)
    return result


@router.get("/purchases", response_model=List[PurchasePublic])
def my_purchases(
    buyer=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all purchases made by the authenticated buyer."""
    return purchase_service.get_buyer_purchases(db, buyer)


@router.get("/purchases/{purchase_id}/download", response_model=DownloadResponse)
def download_dataset(
    purchase_id: str,
    buyer=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a fresh signed URL to download a purchased dataset.
    URL expires after 1 hour — call this endpoint again to refresh.
    """
    return purchase_service.get_download_url(db, purchase_id, buyer)


@router.post("/purchases/{purchase_id}/dispute", response_model=PurchasePublic)
def open_dispute(
    purchase_id: str,
    body: DisputeRequest,
    buyer=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Open a dispute within 48h of purchase. Funds are frozen until resolved."""
    return purchase_service.open_dispute(db, purchase_id, buyer, body.reason)


@router.post("/purchases/{purchase_id}/review", response_model=PurchasePublic)
def leave_review(
    purchase_id: str,
    body: ReviewRequest,
    buyer=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Leave a rating (1–5) and optional review for a completed purchase."""
    return purchase_service.leave_review(db, purchase_id, buyer, body.rating, body.review)


# ── Seller — Stripe onboarding ────────────────────────────────────────────────

@router.get("/seller/onboarding")
def seller_onboarding(
    return_url: str,
    refresh_url: str,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """
    Get the Stripe hosted onboarding URL. Seller completes KYC and bank
    details directly on Stripe — DataMarket never sees this data.
    """
    url = purchase_service.onboard_seller(db, seller, return_url, refresh_url)
    return {"onboarding_url": url}


@router.get("/seller/payout-status")
def seller_payout_status(
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Check if the seller's Stripe account is ready to receive payouts."""
    return purchase_service.get_seller_payout_status(db, seller)


# ── Admin — dispute resolution ────────────────────────────────────────────────

@router.post("/admin/purchases/{purchase_id}/resolve", response_model=PurchasePublic)
def resolve_dispute(
    purchase_id: str,
    favour_buyer: bool,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Admin resolves a dispute.
    - favour_buyer=true  → refund buyer, seller not paid
    - favour_buyer=false → complete purchase, seller gets paid
    """
    return purchase_service.resolve_dispute(db, purchase_id, admin, favour_buyer)


# ── Stripe webhook ────────────────────────────────────────────────────────────

@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db),
):
    """
    Stripe sends events here. We handle:
      - payment_intent.succeeded → complete purchase, release funds
      - payment_intent.payment_failed → cancel purchase
      - account.updated → seller onboarding completed
    """
    payload = await request.body()

    try:
        event = stripe_client.construct_webhook_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        try:
            purchase_service.confirm_payment(db, data["id"])
        except Exception:
            pass  # log and continue — don't let webhook fail

    elif event_type == "payment_intent.payment_failed":
        # Mark purchase as cancelled
        from app.models.purchase import Purchase, PurchaseStatus
        purchase = (
            db.query(Purchase)
            .filter(Purchase.stripe_payment_intent_id == data["id"])
            .first()
        )
        if purchase and purchase.status == PurchaseStatus.PENDING:
            purchase.status = PurchaseStatus.CANCELLED
            db.commit()

    elif event_type == "account.updated":
        # Seller completed Stripe onboarding
        from app.models.user import User
        seller = (
            db.query(User)
            .filter(User.stripe_customer_id == data["id"])
            .first()
        )
        # Could trigger a notification here (future: email)

    return {"received": True}
