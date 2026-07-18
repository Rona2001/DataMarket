"""
Dataset routes:

Public (no auth):
  GET  /datasets               — browse marketplace
  GET  /datasets/{id}          — dataset detail + sample URL

Seller only:
  POST   /datasets             — upload a new dataset
  GET    /datasets/mine        — list my datasets
  PATCH  /datasets/{id}        — update metadata
  POST   /datasets/{id}/publish
  POST   /datasets/{id}/unpublish
  DELETE /datasets/{id}
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller
from app.schemas.dataset import DatasetCreate, DatasetUpdate, DatasetPublic, DatasetDetail, DatasetList
from app.services import dataset_service
from app.models.dataset import DatasetStatus
from app.verification.pipeline import run_verification_background
from app.services.alert_service import send_dataset_alerts
from app.core import notifications

router = APIRouter(prefix="/datasets", tags=["Datasets"])


# ── Public endpoints ──────────────────────────────────────────────────────────

@router.get("", response_model=DatasetList)
def browse_datasets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    free_only: bool = False,
    db: Session = Depends(get_db),
):
    """Browse all published datasets with filtering and pagination."""
    return dataset_service.list_published_datasets(
        db, page, page_size, category, search, min_price, max_price, free_only
    )


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """Get full details for a published dataset (increments view count)."""
    return dataset_service.get_published_dataset(db, dataset_id)


# ── Seller endpoints ──────────────────────────────────────────────────────────

@router.post("", response_model=DatasetPublic, status_code=201)
async def upload_dataset(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="The dataset file (CSV, JSON, Parquet, Excel, ZIP)"),
    # Metadata sent as JSON string in a form field alongside the file
    metadata: str = Form(..., description='JSON string: {"title": "...", "price": 0, ...}'),
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """
    Upload a new dataset. Send as multipart/form-data:
    - `file`: the dataset file
    - `metadata`: JSON string with title, description, price, tags, etc.

    On successful upload the dataset is moved to PENDING_REVIEW and the
    verification pipeline is auto-triggered in the background (spec §3) —
    datasets never sit unprocessed.
    """
    try:
        meta = DatasetCreate(**json.loads(metadata))
    except Exception as e:
        return JSONResponse(status_code=422, content={"detail": f"Invalid metadata: {e}"})

    dataset = await dataset_service.upload_dataset(db, seller, file, meta)

    # Auto-trigger verification: mark pending now, process in the background.
    # (No refresh — it would drop the transient sample_url set by the service.)
    dataset.status = DatasetStatus.PENDING_REVIEW
    db.commit()
    background_tasks.add_task(run_verification_background, str(dataset.id))
    # Upload-received confirmation email (best-effort — spec §18).
    background_tasks.add_task(notifications.upload_received, seller.email, seller.full_name, dataset.title)

    return dataset


@router.get("/mine/list", response_model=List[DatasetPublic])
def my_datasets(
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """List all datasets uploaded by the authenticated seller."""
    return dataset_service.list_seller_datasets(db, seller)


@router.patch("/{dataset_id}", response_model=DatasetPublic)
def update_dataset(
    dataset_id: str,
    updates: DatasetUpdate,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Update dataset metadata (title, price, description, tags…)."""
    return dataset_service.update_dataset(db, dataset_id, seller, updates)


@router.post("/{dataset_id}/publish", response_model=DatasetPublic)
def publish_dataset(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Make a dataset visible on the marketplace and notify category followers (spec §11)."""
    dataset = dataset_service.publish_dataset(db, dataset_id, seller)
    background_tasks.add_task(send_dataset_alerts, str(dataset.id))
    return dataset


@router.post("/{dataset_id}/unpublish", response_model=DatasetPublic)
def unpublish_dataset(
    dataset_id: str,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Pull a dataset from the marketplace (back to DRAFT)."""
    return dataset_service.unpublish_dataset(db, dataset_id, seller)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Permanently delete a dataset and its files from storage."""
    dataset_service.delete_dataset(db, dataset_id, seller)
