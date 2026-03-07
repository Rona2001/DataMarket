from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.purchase import PurchaseStatus


class PurchaseInitiate(BaseModel):
    dataset_id: str


class PurchasePublic(BaseModel):
    id: UUID
    buyer_id: UUID
    dataset_id: UUID
    amount: float
    platform_fee: float
    seller_payout: float
    status: PurchaseStatus
    rating: Optional[float]
    review: Optional[str]
    access_expires_at: Optional[datetime]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class PaymentIntentResponse(BaseModel):
    """Returned to frontend so it can call stripe.confirmPayment()"""
    purchase_id: str
    client_secret: str           # stripe PaymentIntent client_secret
    amount_eur: float
    platform_fee_eur: float
    seller_payout_eur: float
    dataset_title: str


class DownloadResponse(BaseModel):
    """Time-limited signed URL for dataset download."""
    signed_url: str
    expires_in_seconds: int
    checksum: Optional[str]      # buyer can verify file integrity
    dataset_title: str


class DisputeRequest(BaseModel):
    reason: str


class ReviewRequest(BaseModel):
    rating: float
    review: Optional[str] = None

    class Config:
        @classmethod
        def validate_rating(cls, v):
            if not 1.0 <= v <= 5.0:
                raise ValueError("Rating must be between 1 and 5")
            return round(v, 1)
