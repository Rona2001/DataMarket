"""
QualityReport — the free, public lead-magnet report (spec §4).

A dataset owner uploads a file WITHOUT listing it and receives a datrust
quality + PII report for free. The raw file is deleted immediately after
processing; only this metadata row is retained (itself a trust signal).
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, Enum, JSON, Integer

from app.db.session import Base


class ReportStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Public, unguessable token used in the shareable read-only report URL.
    token = Column(String(43), unique=True, nullable=False, index=True)

    # Captured lead (required to receive the report — feeds Brevo).
    email = Column(String(255), nullable=False, index=True)

    # File metadata retained (the file itself is NOT stored).
    filename = Column(String(500), nullable=True)
    data_format = Column(String(20), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    checksum = Column(String(64), nullable=True)

    # Analysis output.
    status = Column(Enum(ReportStatus), default=ReportStatus.PROCESSING, nullable=False)
    quality_score = Column(Float, nullable=True)
    pii_risk_level = Column(String(10), nullable=True)
    report = Column(JSON, nullable=True)          # full analyze_bytes() output

    # Abuse controls.
    ip_address = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<QualityReport {self.email} score={self.quality_score}>"
