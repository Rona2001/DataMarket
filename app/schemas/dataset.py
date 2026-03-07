from pydantic import BaseModel, field_validator
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime
from app.models.dataset import DatasetStatus, DataFormat


# ── Create (form fields submitted alongside the file) ─────────────────────────

class DatasetCreate(BaseModel):
    title: str
    description: str
    price: float
    category: Optional[str] = None
    tags: Optional[List[str]] = []
    license_type: Optional[str] = None
    data_origin: Optional[str] = None
    contains_pii: bool = False
    gdpr_compliant: bool = False
    usage_restrictions: Optional[str] = None
    update_frequency: Optional[str] = None

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v):
        if v < 0:
            raise ValueError("Price cannot be negative")
        return round(v, 2)

    @field_validator("title")
    @classmethod
    def title_length(cls, v):
        if len(v.strip()) < 5:
            raise ValueError("Title must be at least 5 characters")
        return v.strip()


# ── Update ────────────────────────────────────────────────────────────────────

class DatasetUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    license_type: Optional[str] = None
    usage_restrictions: Optional[str] = None
    update_frequency: Optional[str] = None


# ── Responses ─────────────────────────────────────────────────────────────────

class DatasetPublic(BaseModel):
    """Safe to return to any user — no internal storage keys."""
    id: UUID
    seller_id: UUID
    title: str
    slug: str
    description: str
    tags: List[Any]
    category: Optional[str]
    data_format: DataFormat
    num_rows: Optional[int]
    num_columns: Optional[int]
    file_size_bytes: Optional[int]
    schema_info: Optional[Any]
    update_frequency: Optional[str]
    price: float
    is_free: bool
    license_type: Optional[str]
    contains_pii: bool
    gdpr_compliant: bool
    usage_restrictions: Optional[str]
    status: DatasetStatus
    quality_score: Optional[float]
    view_count: int
    download_count: int
    average_rating: Optional[float]
    sample_url: Optional[str] = None   # public URL to CSV sample
    created_at: datetime
    published_at: Optional[datetime]

    class Config:
        from_attributes = True


class DatasetDetail(DatasetPublic):
    """Extended response for the dataset detail page."""
    verification_report: Optional[Any]
    checksum: Optional[str]
    updated_at: datetime


class DatasetList(BaseModel):
    """Paginated list response."""
    items: List[DatasetPublic]
    total: int
    page: int
    page_size: int
    pages: int
