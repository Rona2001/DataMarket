"""
Verification routes:

Seller:
  POST /datasets/{id}/verify        — request verification (submit for review)
  GET  /datasets/{id}/verification  — get verification report for own dataset

Admin:
  POST /admin/datasets/{id}/verify  — trigger verification manually
  GET  /admin/datasets/pending       — list all PENDING_REVIEW datasets
"""
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.core.security import get_current_active_seller, get_current_admin
from app.models.dataset import Dataset, DatasetStatus
from app.schemas.dataset import DatasetPublic
from app.verification.pipeline import run_verification
from app.services.dataset_service import get_dataset_by_id

router = APIRouter(tags=["Verification"])


# ── Seller endpoints ──────────────────────────────────────────────────────────

@router.post("/datasets/{dataset_id}/verify", response_model=DatasetPublic)
def request_verification(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """
    Seller submits a dataset for verification.
    Runs in the background — check /datasets/{id}/verification for results.
    """
    dataset = get_dataset_by_id(db, dataset_id)

    if str(dataset.seller_id) != str(seller.id):
        raise HTTPException(status_code=403, detail="You don't own this dataset")

    if dataset.status not in [DatasetStatus.DRAFT, DatasetStatus.REJECTED]:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset is already '{dataset.status}'. Only DRAFT or REJECTED datasets can be submitted.",
        )

    # Mark as pending immediately so the seller gets feedback
    dataset.status = DatasetStatus.PENDING_REVIEW
    db.commit()
    db.refresh(dataset)

    # Run verification in the background (non-blocking)
    background_tasks.add_task(run_verification, db, dataset)

    return dataset


@router.get("/datasets/{dataset_id}/verification")
def get_verification_report(
    dataset_id: str,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Get the full verification report for a dataset you own."""
    dataset = get_dataset_by_id(db, dataset_id)

    if str(dataset.seller_id) != str(seller.id):
        raise HTTPException(status_code=403, detail="You don't own this dataset")

    return {
        "dataset_id": dataset_id,
        "status": dataset.status,
        "quality_score": dataset.quality_score,
        "report": dataset.verification_report,
    }


# ── Admin endpoints ───────────────────────────────────────────────────────────

@router.post("/admin/datasets/{dataset_id}/verify")
def admin_trigger_verification(
    dataset_id: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Admin manually triggers verification on any dataset."""
    dataset = get_dataset_by_id(db, dataset_id)
    report = run_verification(db, dataset)  # synchronous for admin
    db.refresh(dataset)

    return {
        "dataset_id": dataset_id,
        "new_status": dataset.status,
        "quality_score": dataset.quality_score,
        "report": report,
    }


@router.get("/admin/datasets/pending", response_model=List[DatasetPublic])
def list_pending_datasets(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """List all datasets currently awaiting verification."""
    return (
        db.query(Dataset)
        .filter(Dataset.status == DatasetStatus.PENDING_REVIEW)
        .order_by(Dataset.updated_at.asc())
        .all()
    )


@router.get("/admin/datasets/rejected", response_model=List[DatasetPublic])
def list_rejected_datasets(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """List all rejected datasets for review."""
    return (
        db.query(Dataset)
        .filter(Dataset.status == DatasetStatus.REJECTED)
        .order_by(Dataset.updated_at.desc())
        .all()
    )
