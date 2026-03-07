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
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller
from app.schemas.dataset import DatasetCreate, DatasetUpdate, DatasetPublic, DatasetDetail, DatasetList
from app.services import dataset_service

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
    """
    try:
        meta = DatasetCreate(**json.loads(metadata))
    except Exception as e:
        return JSONResponse(status_code=422, content={"detail": f"Invalid metadata: {e}"})

    return await dataset_service.upload_dataset(db, seller, file, meta)


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
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Make a dataset visible on the marketplace."""
    return dataset_service.publish_dataset(db, dataset_id, seller)


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
