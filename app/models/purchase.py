import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.db.session import Base


class PurchaseStatus(str, enum.Enum):
    PENDING = "pending"           # payment initiated, funds in escrow
    VERIFYING = "verifying"       # dataset being verified post-purchase
    COMPLETED = "completed"       # funds released to seller, download ready
    DISPUTED = "disputed"         # buyer raised issue
    REFUNDED = "refunded"         # funds returned to buyer
    CANCELLED = "cancelled"


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False)

    # Financial
    amount = Column(Float, nullable=False)           # amount paid in EUR
    platform_fee = Column(Float, nullable=False)     # 10% commission
    seller_payout = Column(Float, nullable=False)    # amount - fee

    # Escrow / payment tracking
    status = Column(Enum(PurchaseStatus), default=PurchaseStatus.PENDING)
    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True)
    stripe_transfer_id = Column(String(255), nullable=True)  # payout to seller

    # Access control — the buyer gets a time-limited signed URL
    # We don't store the URL itself, we regenerate it on demand
    access_expires_at = Column(DateTime, nullable=True)      # when download access expires

    # Dispute management
    dispute_reason = Column(Text, nullable=True)
    dispute_opened_at = Column(DateTime, nullable=True)
    dispute_resolved_at = Column(DateTime, nullable=True)

    # Review (left by buyer after purchase)
    rating = Column(Float, nullable=True)            # 1-5
    review = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    buyer = relationship("User", back_populates="purchases")
    dataset = relationship("Dataset", back_populates="purchases")

    def __repr__(self):
        return f"<Purchase {self.id} | {self.status}>"
