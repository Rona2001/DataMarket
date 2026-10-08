"""
Chat log (spec §14) — one row per chatbot message, for per-user rate limiting
and usage analytics. Conversations themselves are not persisted (the frontend
holds history and replays it each turn).
"""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.session import Base


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ChatQuestion(Base):
    """
    What buyers ask Datia about a dataset, for the seller's insights panel
    ("questions your listing could not answer"). Deliberately anonymous: no
    user id, so a seller can never tie a question to a buyer.
    """
    __tablename__ = "chat_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answered = Column(Boolean, default=True, nullable=False)   # False: the listing's data could not answer it
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
