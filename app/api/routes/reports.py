"""
Free Quality Report routes (spec §4) — PUBLIC, no authentication.

  POST /reports          — upload a file + email, get a free quality/PII report
  GET  /reports/{token}  — shareable read-only report view

The lead magnet: gives the platform single-side utility with zero buyers and
turns the verification pipeline into an acquisition weapon. The raw file is
analysed in memory and never stored.
"""
import re

from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, Request, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.core import brevo
from app.schemas.report import QualityReportPublic, QualityReportCreated
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Quality Report"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _client_ip(request: Request) -> str | None:
    # Honour the first hop of X-Forwarded-For (Render/Vercel proxy) then fall back.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _share_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/report/{token}"


@router.post("", response_model=QualityReportCreated, status_code=201)
async def create_quality_report(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Dataset file to analyse (CSV, JSON, Parquet, Excel, ZIP)"),
    email: str = Form(..., description="Email to receive the report — feeds the waitlist"),
    db: Session = Depends(get_db),
):
    """
    Upload a dataset and receive a free datrust quality + PII report.
    No account required. The file is analysed in memory and immediately discarded.
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Please provide a valid email address.")

    report = await report_service.create_report(db, email, file, ip=_client_ip(request))

    # Capture the lead in Brevo (non-blocking, graceful if unconfigured).
    background_tasks.add_task(
        brevo.add_contact,
        email,
        {
            "SOURCE": "free_quality_report",
            "LAST_REPORT_SCORE": report.quality_score,
        },
    )

    base = QualityReportPublic.model_validate(report).model_dump()
    return QualityReportCreated(**base, share_url=_share_url(report.token))


@router.get("/{token}", response_model=QualityReportPublic)
def get_quality_report(token: str, db: Session = Depends(get_db)):
    """Public, read-only view of a previously generated report."""
    return report_service.get_report_by_token(db, token)
