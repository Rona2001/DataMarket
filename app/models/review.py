"""
Reviews & Ratings (spec §13) — post-purchase only.

Only a verified buyer (a COMPLETED purchase) can review a dataset, one review
per purchase, which keeps the signal honest. The seller may respond once.
Feeds Dataset.average_rating → the seller profile (§12) and dataset detail page.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, Text, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    buyer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # One review per purchase — the unique link that gates and de-dupes.
    purchase_id = Column(UUID(as_uuid=True), ForeignKey("purchases.id"), nullable=False, unique=True)

    rating = Column(Integer, nullable=False)          # 1–5
    tags = Column(JSON, default=list)                 # structured tags (see schema)
    text = Column(Text, nullable=True)                # short free text

    # Seller may respond once.
    seller_response = Column(Text, nullable=True)
    seller_responded_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    buyer = relationship("User")
    dataset = relationship("Dataset")

    def __repr__(self):
        return f"<Review dataset={self.dataset_id} rating={self.rating}>"
