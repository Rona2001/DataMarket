"""
Premium subscription (€10/month) — one row per user, mirroring the state of
their Stripe subscription. `users.is_premium` stays the flag the rest of the
app reads; this table is what keeps it in sync with Stripe.

Kept in its own table because users.stripe_customer_id already holds the
seller's Stripe Connect account id, which is a different object.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.db.session import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)

    stripe_customer_id = Column(String(255), nullable=True, index=True)
    stripe_subscription_id = Column(String(255), nullable=True, index=True)
    status = Column(String(50), nullable=True)             # Stripe status: active, past_due, canceled…
    current_period_end = Column(DateTime, nullable=True)   # paid through (UTC)
    cancel_at_period_end = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
