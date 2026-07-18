import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.session import Base


class Favorite(Base):
    """A user's saved/favourited dataset (spec: buyer wishlist)."""
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "dataset_id", name="uq_favorite_user_dataset"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
