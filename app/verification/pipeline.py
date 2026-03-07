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
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetStatus
from app.core import storage
from app.core.config import settings
from app.utils.file_utils import load_dataframe
from app.verification.pii_detector import scan_for_pii
from app.verification.quality_scorer import score_dataset


# Score thresholds
VERIFICATION_PASS_SCORE = 60.0
AUTO_REJECT_PII_RISK = "high"


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

    # ── Step 2: Load into DataFrame ───────────────────────────────────────────
    df = load_dataframe(file_bytes, dataset.data_format)

    if df is None:
        report["steps"]["parse"] = {
            "status": "skipped",
            "reason": "ZIP or unreadable format — structural checks skipped.",
        }
        # For ZIP files, do a lightweight pass without DataFrame analysis
        _mark_verified_zip(db, dataset, report)
        return report

    report["steps"]["parse"] = {
        "status": "ok",
        "num_rows": len(df),
        "num_columns": len(df.columns),
    }

    # ── Step 3: PII scan ──────────────────────────────────────────────────────
    pii_report = scan_for_pii(df)
    report["steps"]["pii_scan"] = pii_report

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

    # ── Step 4: Quality scoring ───────────────────────────────────────────────
    quality_result = score_dataset(
        df,
        pii_report,
        seller_declared_gdpr=dataset.gdpr_compliant,
        seller_declared_no_pii=not dataset.contains_pii,
    )
    report["steps"]["quality_score"] = quality_result

    # ── Step 5: Final verdict ─────────────────────────────────────────────────
    if quality_result["score"] >= VERIFICATION_PASS_SCORE:
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
