"""
Dataset service — all business logic for dataset lifecycle.

Upload flow:
  1. Validate file (extension, size)
  2. Compute SHA-256 checksum
  3. Load into DataFrame → extract stats + generate sample
  4. Upload full file to PRIVATE bucket
  5. Upload sample to PUBLIC bucket
  6. Create DB record (status=DRAFT)
  7. Return dataset object

Publish flow:
  - Seller explicitly publishes → status=PUBLISHED
  - Or: submit for verification → status=PENDING_REVIEW (Step 3)
"""
import uuid
import re
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, UploadFile

from app.models.dataset import Dataset, DatasetStatus
from app.models.user import User
from app.schemas.dataset import DatasetCreate, DatasetUpdate
from app.core.config import settings
from app.core import storage
from app.utils.file_utils import (
    validate_extension,
    validate_size,
    compute_checksum,
    load_dataframe,
    extract_stats,
    generate_sample,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text


def unique_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    existing = db.query(Dataset).filter(Dataset.slug == slug).first()
    if existing:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    return slug


# ── Upload ────────────────────────────────────────────────────────────────────

async def upload_dataset(
    db: Session,
    seller: User,
    file: UploadFile,
    metadata: DatasetCreate,
) -> Dataset:
    # 1. Read file bytes
    data = await file.read()

    # 2. Validate
    try:
        data_format = validate_extension(file.filename)
        validate_size(len(data))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. Checksum
    checksum = compute_checksum(data)

    # 4. Prevent duplicate uploads (same file from same seller)
    duplicate = (
        db.query(Dataset)
        .filter(Dataset.seller_id == seller.id, Dataset.checksum == checksum)
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="You have already uploaded a dataset with identical content.",
        )

    # 5. Build dataset ID and storage keys
    dataset_id = str(uuid.uuid4())
    seller_id = str(seller.id)
    storage_key = storage.build_storage_key(seller_id, dataset_id, file.filename)
    sample_key = storage.build_storage_key(seller_id, dataset_id, "sample.csv")

    # 6. Extract stats + generate sample (best effort — won't fail upload if it errors)
    stats = {}
    sample_bytes = None
    df = load_dataframe(data, data_format)
    if df is not None:
        try:
            stats = extract_stats(df)
            sample_bytes = generate_sample(df)
        except Exception:
            pass

    # 7. Upload to Supabase Storage
    content_type = file.content_type or "application/octet-stream"
    storage.upload_file(settings.SUPABASE_STORAGE_BUCKET, storage_key, data, content_type)

    sample_url = None
    if sample_bytes:
        storage.upload_file(
            settings.SUPABASE_SAMPLE_BUCKET, sample_key, sample_bytes, "text/csv"
        )
        sample_url = storage.get_public_sample_url(sample_key)

    # 8. Create DB record
    dataset = Dataset(
        id=dataset_id,
        seller_id=seller.id,
        title=metadata.title,
        slug=unique_slug(db, metadata.title),
        description=metadata.description,
        price=metadata.price,
        is_free=metadata.price == 0,
        category=metadata.category,
        tags=metadata.tags or [],
        license_type=metadata.license_type,
        data_origin=metadata.data_origin,
        contains_pii=metadata.contains_pii,
        gdpr_compliant=metadata.gdpr_compliant,
        usage_restrictions=metadata.usage_restrictions,
        update_frequency=metadata.update_frequency,
        data_format=data_format,
        num_rows=stats.get("num_rows"),
        num_columns=stats.get("num_columns"),
        file_size_bytes=len(data),
        schema_info=stats,
        checksum=checksum,
        storage_key=storage_key,
        sample_storage_key=sample_key if sample_bytes else None,
        status=DatasetStatus.DRAFT,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    # Attach sample URL for the response (not stored in DB — regenerated on demand)
    dataset.sample_url = sample_url
    return dataset


# ── Publish / Unpublish ───────────────────────────────────────────────────────

def publish_dataset(db: Session, dataset_id: str, seller: User) -> Dataset:
    dataset = _get_owned_dataset(db, dataset_id, seller)
    if dataset.status not in [DatasetStatus.DRAFT, DatasetStatus.VERIFIED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish a dataset with status '{dataset.status}'.",
        )
    dataset.status = DatasetStatus.PUBLISHED
    dataset.published_at = datetime.utcnow()
    db.commit()
    db.refresh(dataset)
    return dataset


def unpublish_dataset(db: Session, dataset_id: str, seller: User) -> Dataset:
    dataset = _get_owned_dataset(db, dataset_id, seller)
    dataset.status = DatasetStatus.DRAFT
    db.commit()
    db.refresh(dataset)
    return dataset


# ── Update ────────────────────────────────────────────────────────────────────

def update_dataset(db: Session, dataset_id: str, seller: User, updates: DatasetUpdate) -> Dataset:
    dataset = _get_owned_dataset(db, dataset_id, seller)
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(dataset, field, value)
    if updates.price is not None:
        dataset.is_free = updates.price == 0
    db.commit()
    db.refresh(dataset)
    return dataset


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_dataset(db: Session, dataset_id: str, seller: User) -> None:
    dataset = _get_owned_dataset(db, dataset_id, seller)

    # Remove files from storage
    if dataset.storage_key:
        try:
            storage.delete_file(settings.SUPABASE_STORAGE_BUCKET, dataset.storage_key)
        except Exception:
            pass
    if dataset.sample_storage_key:
        try:
            storage.delete_file(settings.SUPABASE_SAMPLE_BUCKET, dataset.sample_storage_key)
        except Exception:
            pass

    db.delete(dataset)
    db.commit()


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def get_dataset_by_id(db: Session, dataset_id: str) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def get_published_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.status == DatasetStatus.PUBLISHED,
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Increment view count
    dataset.view_count += 1
    db.commit()
    return dataset


def list_published_datasets(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    category: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    free_only: bool = False,
) -> dict:
    query = db.query(Dataset).filter(Dataset.status == DatasetStatus.PUBLISHED)

    if category:
        query = query.filter(Dataset.category == category)
    if search:
        query = query.filter(Dataset.title.ilike(f"%{search}%"))
    if free_only:
        query = query.filter(Dataset.is_free == True)
    if min_price is not None:
        query = query.filter(Dataset.price >= min_price)
    if max_price is not None:
        query = query.filter(Dataset.price <= max_price)

    total = query.count()
    items = query.order_by(Dataset.published_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),  # ceiling division
    }


def list_seller_datasets(db: Session, seller: User) -> list:
    return (
        db.query(Dataset)
        .filter(Dataset.seller_id == seller.id)
        .order_by(Dataset.created_at.desc())
        .all()
    )


# ── Private ───────────────────────────────────────────────────────────────────

def _get_owned_dataset(db: Session, dataset_id: str, seller: User) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if str(dataset.seller_id) != str(seller.id):
        raise HTTPException(status_code=403, detail="You don't own this dataset")
    return dataset
