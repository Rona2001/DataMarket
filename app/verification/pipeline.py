"""
Verification Pipeline — orchestrates the full verification flow.

Steps:
  1. Fetch dataset file from Supabase Storage
  2. Load into DataFrame
  3. Run PII scan
  4. Run quality scoring
  5. Update Dataset record with results
  6. Set status → VERIFIED or REJECTED

This can be called:
  - Synchronously (on-demand by admin/seller)
  - Asynchronously via a background task after upload (future: Celery / Supabase Edge Functions)
"""
from datetime import datetime
import numpy as np
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetStatus
from app.core import storage
from app.core.config import settings
from app.db.session import SessionLocal
from app.utils.file_utils import load_dataframe
from app.verification.pii_detector import scan_for_pii
from app.verification.quality_scorer import score_dataset


# Score thresholds
VERIFICATION_PASS_SCORE = 60.0
AUTO_REJECT_PII_RISK = "high"


def _to_native(obj):
    """
    Recursively convert numpy scalars/arrays to native Python types so the
    report is JSON-serializable (pandas leaves np.float64 / np.bool_ around,
    which neither the JSON DB column nor the API response can serialize).
    """
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _to_native(obj.tolist())
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def analyze_bytes(
    file_bytes: bytes,
    data_format,
    *,
    seller_declared_gdpr: bool = False,
    seller_declared_no_pii: bool = False,
) -> dict:
    """
    Pure analysis: parse → PII scan → quality score. No DB, no storage.

    Shared by the dataset verification pipeline (run_verification) and the
    public free quality report (spec §4), which runs on in-memory bytes and
    never persists the file.

    Returns:
        {
          "parseable": bool,
          "steps": { "parse", "pii_scan", "quality_score" },
          "quality_score": float | None,
          "label": str | None,
          "pii_risk_level": str,
          "passed": bool,
        }
    """
    result = {
        "parseable": True,
        "steps": {},
        "quality_score": None,
        "label": None,
        "pii_risk_level": "none",
        "passed": False,
    }

    df = load_dataframe(file_bytes, data_format)
    if df is None:
        result["parseable"] = False
        result["steps"]["parse"] = {
            "status": "skipped",
            "reason": "ZIP or unreadable format — structural checks skipped.",
        }
        return _to_native(result)

    result["steps"]["parse"] = {
        "status": "ok",
        "num_rows": len(df),
        "num_columns": len(df.columns),
    }

    pii_report = scan_for_pii(df)
    result["steps"]["pii_scan"] = pii_report
    result["pii_risk_level"] = pii_report["risk_level"]

    quality_result = score_dataset(
        df,
        pii_report,
        seller_declared_gdpr=seller_declared_gdpr,
        seller_declared_no_pii=seller_declared_no_pii,
    )
    result["steps"]["quality_score"] = quality_result
    result["quality_score"] = quality_result["score"]
    result["label"] = quality_result["label"]
    result["passed"] = quality_result["score"] >= VERIFICATION_PASS_SCORE

    return _to_native(result)


def run_verification_background(dataset_id: str) -> None:
    """
    Background-task entry point. Opens its own DB session because the
    request-scoped session is already closed by the time this runs.

    Wired into the upload flow so datasets never sit in pending_review
    without processing (see functional spec §3).
    """
    db = SessionLocal()
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if dataset is None:
            return
        run_verification(db, dataset)
        # Email the seller the verification result (best-effort — spec §18).
        from app.core import notifications
        notifications.verification_done(db, dataset_id)
    finally:
        db.close()


def run_verification(db: Session, dataset: Dataset) -> dict:
    """
    Run the full verification pipeline on a dataset.
    Updates the Dataset record in-place and returns the full report.
    """
    report = {
        "dataset_id": str(dataset.id),
        "verified_at": datetime.utcnow().isoformat(),
        "steps": {},
        "passed": False,
        "rejection_reason": None,
    }

    # ── Step 1: Fetch file from storage ──────────────────────────────────────
    try:
        signed_url = storage.generate_signed_url(
            settings.SUPABASE_STORAGE_BUCKET,
            dataset.storage_key,
            expires_in=300,  # 5 min — just enough to download for verification
        )
        import httpx
        response = httpx.get(signed_url, timeout=60)
        response.raise_for_status()
        file_bytes = response.content
    except Exception as e:
        report["steps"]["fetch"] = {"status": "error", "error": str(e)}
        _mark_failed(db, dataset, f"Could not fetch dataset file: {e}")
        return report

    report["steps"]["fetch"] = {"status": "ok", "size_bytes": len(file_bytes)}

    # ── Steps 2–4: parse → PII scan → quality score (shared analysis) ─────────
    analysis = analyze_bytes(
        file_bytes,
        dataset.data_format,
        seller_declared_gdpr=dataset.gdpr_compliant,
        seller_declared_no_pii=not dataset.contains_pii,
    )
    report["steps"].update(analysis["steps"])

    # ZIP / unreadable formats can't be structurally scanned.
    if not analysis["parseable"]:
        _mark_verified_zip(db, dataset, report)
        return report

    pii_report = analysis["steps"]["pii_scan"]

    # Hard reject if high PII risk and seller didn't declare GDPR compliance
    if (
        pii_report["risk_level"] == AUTO_REJECT_PII_RISK
        and not dataset.gdpr_compliant
    ):
        report["rejection_reason"] = (
            "High PII risk detected and GDPR compliance not declared. "
            "Please anonymize the dataset or confirm GDPR compliance before resubmitting."
        )
        report["steps"]["pii_scan"]["action"] = "auto_rejected"
        _mark_failed(db, dataset, report["rejection_reason"], pii_report)
        return report

    # Update PII flag in DB based on scan
    if pii_report["pii_detected"] and not dataset.contains_pii:
        dataset.contains_pii = True

    # ── Step 5: Final verdict ─────────────────────────────────────────────────
    quality_result = analysis["steps"]["quality_score"]
    if analysis["passed"]:
        report["passed"] = True
        _mark_verified(db, dataset, quality_result["score"], report)
    else:
        report["rejection_reason"] = (
            f"Quality score {quality_result['score']}/100 is below the minimum threshold "
            f"of {VERIFICATION_PASS_SCORE}. "
            "Recommendations: " + "; ".join(quality_result["recommendations"][:3])
        )
        _mark_failed(db, dataset, report["rejection_reason"], report)

    return report


# ── DB state transitions ──────────────────────────────────────────────────────

def _mark_verified(db: Session, dataset: Dataset, score: float, report: dict) -> None:
    dataset.status = DatasetStatus.VERIFIED
    dataset.quality_score = score
    dataset.verification_report = report
    db.commit()


def _mark_verified_zip(db: Session, dataset: Dataset, report: dict) -> None:
    """ZIPs can't be fully scanned — give a neutral score and mark as reviewed."""
    dataset.status = DatasetStatus.VERIFIED
    dataset.quality_score = 65.0  # neutral score for un-inspectable formats
    dataset.verification_report = report
    db.commit()


def _mark_failed(
    db: Session,
    dataset: Dataset,
    reason: str,
    report: dict = None,
) -> None:
    dataset.status = DatasetStatus.REJECTED
    dataset.quality_score = 0.0
    dataset.verification_report = report or {"rejection_reason": reason}
    db.commit()
