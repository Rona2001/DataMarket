from pydantic import BaseModel, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from app.models.dataset_request import RequestStatus


# ── Allowed survey values (kept in sync with the frontend survey) ──────────────

DATA_TYPES = {"tabular", "text_corpus", "images", "time_series", "geospatial", "other"}
VOLUMES = {"<10k", "10k-1M", ">1M"}
INTENDED_USES = {"academic", "prototyping", "commercial"}
RGPD_CONSTRAINTS = {"fully_anonymised", "pseudonymised_ok", "no_personal_data"}
BUDGET_RANGES = {"0-50", "50-300", "300-2000", "2000+"}


# ── Create / Update ─────────────────────────────────────────────────────────────

class RequestCreate(BaseModel):
    domain: str
    data_types: List[str] = []
    volume: str
    intended_use: str
    rgpd_constraint: str
    budget_range: str
    deadline: Optional[str] = None
    free_text: Optional[str] = None

    @field_validator("domain")
    @classmethod
    def domain_present(cls, v):
        if not v or not v.strip():
            raise ValueError("A domain / thématique is required")
        return v.strip()

    @field_validator("data_types")
    @classmethod
    def valid_data_types(cls, v):
        bad = [x for x in v if x not in DATA_TYPES]
        if bad:
            raise ValueError(f"Invalid data type(s): {', '.join(bad)}")
        return v

    @field_validator("volume")
    @classmethod
    def valid_volume(cls, v):
        if v not in VOLUMES:
            raise ValueError(f"volume must be one of {sorted(VOLUMES)}")
        return v

    @field_validator("intended_use")
    @classmethod
    def valid_use(cls, v):
        if v not in INTENDED_USES:
            raise ValueError(f"intended_use must be one of {sorted(INTENDED_USES)}")
        return v

    @field_validator("rgpd_constraint")
    @classmethod
    def valid_rgpd(cls, v):
        if v not in RGPD_CONSTRAINTS:
            raise ValueError(f"rgpd_constraint must be one of {sorted(RGPD_CONSTRAINTS)}")
        return v

    @field_validator("budget_range")
    @classmethod
    def valid_budget(cls, v):
        if v not in BUDGET_RANGES:
            raise ValueError(f"budget_range must be one of {sorted(BUDGET_RANGES)}")
        return v


class RequestUpdate(BaseModel):
    domain: Optional[str] = None
    data_types: Optional[List[str]] = None
    volume: Optional[str] = None
    intended_use: Optional[str] = None
    rgpd_constraint: Optional[str] = None
    budget_range: Optional[str] = None
    deadline: Optional[str] = None
    free_text: Optional[str] = None


# ── Responses ───────────────────────────────────────────────────────────────────

class RequestResponsePublic(BaseModel):
    id: UUID
    seller_id: UUID
    dataset_id: Optional[UUID]
    message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RequestPublic(BaseModel):
    id: UUID
    title: str
    domain: Optional[str]
    data_types: List[str]
    volume: Optional[str]
    intended_use: Optional[str]
    rgpd_constraint: Optional[str]
    budget_range: Optional[str]
    deadline: Optional[str]
    free_text: Optional[str]
    status: RequestStatus
    response_count: int = 0
    created_at: datetime
    published_at: Optional[datetime]

    class Config:
        from_attributes = True


class RequestList(BaseModel):
    items: List[RequestPublic]
    total: int
    page: int
    page_size: int
    pages: int


class RequestResponseCreate(BaseModel):
    dataset_id: Optional[UUID] = None
    message: Optional[str] = None
