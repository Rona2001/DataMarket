"""
Category Alerts / 'Notify Me' (spec §11).

Buyers (and sellers, for the request board) follow categories and get an email
when a matching verified dataset is published — or a matching request goes live.
At sub-50-dataset scale this turns the empty-marketplace problem into a
re-engagement channel.
"""
import uuid
import secrets
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


def _token() -> str:
    return secrets.token_urlsafe(24)


class CategoryFollow(Base):
    __tablename__ = "category_follows"
    __table_args__ = (UniqueConstraint("user_id", "category", name="uq_user_category"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)

    # Unguessable token for RGPD one-click unsubscribe from email links.
    unsubscribe_token = Column(String(43), unique=True, nullable=False, default=_token)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")

    def __repr__(self):
        return f"<CategoryFollow user={self.user_id} category={self.category}>"


class AlertLog(Base):
    """
    One row per alert email sent. Powers the max-1-email/day-per-user throttle
    (protects sender reputation) and provides an audit trail.
    """
    __tablename__ = "alert_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(30), nullable=False, default="dataset")  # "dataset" | "request"
    ref_id = Column(String(64), nullable=True)                    # dataset/request id the alert was about
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<AlertLog user={self.user_id} kind={self.kind} at={self.sent_at}>"
