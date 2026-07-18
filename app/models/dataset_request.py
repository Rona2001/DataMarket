"""
Dataset Request Board (spec §10) — survey-based buyer demand.

Buyers describe the dataset they need through a short guided survey; the answers
become a standardised, public request card that sellers can browse and respond
to. Makes the marketplace useful even with a small catalogue, and every
submission is a structured market-research data point.
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class RequestStatus(str, enum.Enum):
    DRAFT = "draft"                 # created, editable by the requester before it goes live
    PENDING_REVIEW = "pending"      # submitted, awaiting moderation
    PUBLISHED = "published"         # live on the public board
    FULFILLED = "fulfilled"         # requester marked it satisfied
    REJECTED = "rejected"           # moderation rejected (spam / prohibited data)
    ARCHIVED = "archived"


class DatasetRequest(Base):
    __tablename__ = "dataset_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Survey answers (Q1–Q8).
    domain = Column(String(100), nullable=True)             # Q1 category / thématique
    data_types = Column(JSON, default=list)                 # Q2 ["tabular", "text_corpus", ...]
    volume = Column(String(50), nullable=True)              # Q3 "<10k" | "10k-1M" | ">1M"
    intended_use = Column(String(50), nullable=True)        # Q4 academic | prototyping | commercial
    rgpd_constraint = Column(String(50), nullable=True)     # Q5 anonymised / pseudonymised / no_personal_data
    budget_range = Column(String(50), nullable=True)        # Q6 "0-50" | "50-300" | "300-2000" | "2000+"
    deadline = Column(String(100), nullable=True)           # Q7 free-form deadline
    free_text = Column(Text, nullable=True)                 # Q8 "anything specific we did not ask about"

    # Generated, normalised card title (e.g. "Corpus NLP français · <1M lignes · usage commercial · 300–2 000 €").
    title = Column(String(300), nullable=False)

    status = Column(Enum(RequestStatus), default=RequestStatus.DRAFT, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    requester = relationship("User")
    responses = relationship("RequestResponse", back_populates="request", cascade="all, delete-orphan")

    @property
    def response_count(self) -> int:
        return len(self.responses)

    def __repr__(self):
        return f"<DatasetRequest '{self.title}' ({self.status})>"


class RequestResponse(Base):
    """
    A seller clicking 'I have this' on a request. Structured, platform-mediated
    response — never open messaging (see spec annex on disintermediation).
    """
    __tablename__ = "request_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("dataset_requests.id"), nullable=False, index=True)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)  # optional listing offered

    message = Column(Text, nullable=True)   # short structured note ("I have a 200k-row FR NLP corpus, RGPD-clean")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    request = relationship("DatasetRequest", back_populates="responses")
    seller = relationship("User")

    def __repr__(self):
        return f"<RequestResponse request={self.request_id} seller={self.seller_id}>"
