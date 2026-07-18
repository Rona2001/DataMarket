"""
Free Quality Report service (spec §4).

Public, no-auth flow: upload → email capture → run the shared analysis
pipeline → store report metadata → return a shareable token.

Trust guarantees baked in:
  - The raw file is NEVER persisted (analysed in memory, then discarded).
  - Only report metadata is retained.
  - Rate limited per email (per month) and per IP (per hour).
"""
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.quality_report import QualityReport, ReportStatus
from app.utils.file_utils import validate_extension, compute_checksum
from app.verification.pipeline import analyze_bytes


def _check_rate_limits(db: Session, email: str, ip: str | None) -> None:
    now = datetime.utcnow()

    month_ago = now - timedelta(days=30)
    email_count = (
        db.query(QualityReport)
        .filter(QualityReport.email == email, QualityReport.created_at >= month_ago)
        .count()
    )
    if email_count >= settings.FREE_REPORTS_PER_EMAIL_PER_MONTH:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've reached the free limit of "
                f"{settings.FREE_REPORTS_PER_EMAIL_PER_MONTH} reports this month. "
                "List a dataset on datrust for unlimited verification."
            ),
        )

    if ip:
        hour_ago = now - timedelta(hours=1)
        ip_count = (
            db.query(QualityReport)
            .filter(QualityReport.ip_address == ip, QualityReport.created_at >= hour_ago)
            .count()
        )
        if ip_count >= settings.FREE_REPORTS_PER_IP_PER_HOUR:
            raise HTTPException(
                status_code=429,
                detail="Too many reports from this network. Please try again later.",
            )


async def create_report(
    db: Session,
    email: str,
    file: UploadFile,
    ip: str | None = None,
) -> QualityReport:
    # 1. Validate file type + size (smaller cap than paid uploads).
    try:
        data_format = validate_extension(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    data = await file.read()
    max_bytes = settings.REPORT_MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(data) / 1024 / 1024:.1f} MB). "
                f"Free reports are capped at {settings.REPORT_MAX_UPLOAD_MB} MB."
            ),
        )
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    # 2. Rate limits.
    _check_rate_limits(db, email, ip)

    # 3. Analyse in memory — the file is never written to storage.
    checksum = compute_checksum(data)
    report_row = QualityReport(
        token=secrets.token_urlsafe(32),
        email=email,
        filename=file.filename,
        data_format=data_format.value,
        file_size_bytes=len(data),
        checksum=checksum,
        ip_address=ip,
        status=ReportStatus.PROCESSING,
    )

    try:
        analysis = analyze_bytes(data, data_format)
        report_row.report = analysis
        report_row.quality_score = analysis.get("quality_score")
        report_row.pii_risk_level = analysis.get("pii_risk_level")
        report_row.status = ReportStatus.COMPLETED
    except Exception as e:
        report_row.status = ReportStatus.FAILED
        report_row.report = {"error": str(e)}
    finally:
        # `data` goes out of scope here — nothing is persisted to storage.
        del data

    db.add(report_row)
    db.commit()
    db.refresh(report_row)
    return report_row


def get_report_by_token(db: Session, token: str) -> QualityReport:
    report = db.query(QualityReport).filter(QualityReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
