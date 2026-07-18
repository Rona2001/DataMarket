from pydantic import BaseModel, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime


# Structured tags a reviewer can attach (kept in sync with the frontend).
REVIEW_TAGS = {
    "as_described",
    "clean_schema",
    "good_documentation",
    "good_value",
    "responsive_seller",
}


class ReviewCreate(BaseModel):
    rating: int
    tags: List[str] = []
    text: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("rating must be between 1 and 5")
        return v

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, v):
        bad = [t for t in v if t not in REVIEW_TAGS]
        if bad:
            raise ValueError(f"Invalid tag(s): {', '.join(bad)}")
        return v


class ReviewRespond(BaseModel):
    response: str

    @field_validator("response")
    @classmethod
    def non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Response cannot be empty")
        return v.strip()


class ReviewPublic(BaseModel):
    id: UUID
    dataset_id: UUID
    rating: int
    tags: List[str]
    text: Optional[str]
    reviewer_name: Optional[str] = None
    seller_response: Optional[str]
    seller_responded_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewEligibility(BaseModel):
    can_review: bool
    reason: str
