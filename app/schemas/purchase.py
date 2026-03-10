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
    """Returned to frontend so it can call stripe.confirmPayment()
    For free datasets, Stripe fields are None and signed_url is provided directly."""
    purchase_id: str
    client_secret: Optional[str] = None     # None for free datasets
    amount_eur: Optional[float] = None
    platform_fee_eur: Optional[float] = None
    seller_payout_eur: Optional[float] = None
    dataset_title: str
    is_free: Optional[bool] = False
    signed_url: Optional[str] = None        # provided immediately for free datasets
    expires_in_seconds: Optional[int] = None


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