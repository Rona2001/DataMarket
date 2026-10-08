"""
Premium subscription routes (€10/month):

  GET  /billing/status     — current plan, renewal date, cancellation state
  POST /billing/checkout   — get the Stripe Checkout URL to subscribe
  POST /billing/sync       — confirm the subscription after returning from Checkout
  POST /billing/cancel     — cancel at the end of the paid month
  POST /billing/resume     — undo a pending cancellation
  POST /billing/portal     — Stripe page to change the card / get invoices

Stripe webhooks for subscriptions arrive on the shared /webhooks/stripe endpoint.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.services import billing_service

router = APIRouter(prefix="/billing", tags=["Billing"])


class BillingStatus(BaseModel):
    is_premium: bool
    status: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    price_eur: float


class OriginBody(BaseModel):
    origin: Optional[str] = None       # window.location.origin, checked against the CORS allow-list


class SyncBody(BaseModel):
    session_id: Optional[str] = None


@router.get("/status", response_model=BillingStatus)
def billing_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.get_status(db, user)


@router.post("/checkout")
def start_checkout(body: OriginBody, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.start_checkout(db, user, body.origin)


@router.post("/sync", response_model=BillingStatus)
def sync_subscription(body: SyncBody, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.sync(db, user, body.session_id)


@router.post("/cancel", response_model=BillingStatus)
def cancel_subscription(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.set_cancel(db, user, True)


@router.post("/resume", response_model=BillingStatus)
def resume_subscription(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.set_cancel(db, user, False)


@router.post("/portal")
def billing_portal(body: OriginBody, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return billing_service.open_portal(db, user, body.origin)
