from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

from app.models.quality_report import ReportStatus


class QualityReportPublic(BaseModel):
    """Shareable, read-only report view — no email or IP exposed."""
    token: str
    status: ReportStatus
    filename: Optional[str]
    data_format: Optional[str]
    file_size_bytes: Optional[int]
    checksum: Optional[str]
    quality_score: Optional[float]
    pii_risk_level: Optional[str]
    report: Optional[Any]
    created_at: datetime

    class Config:
        from_attributes = True


class QualityReportCreated(QualityReportPublic):
    """Returned to the uploader — adds the shareable URL."""
    share_url: str
