"""
Seller Quality Profile (spec §12).

A public, shareable page per seller showing their track record — dataset count,
mean quality score, sales, ratings. Host-profile trust was a bigger unlock for
Airbnb than any analytics feature; the same logic applies here.

  GET /sellers/{seller_id}   — public profile + aggregates

Aggregates are computed on read (fine at sub-1000-dataset scale; move to
nightly/on-write later if needed).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.dataset import Dataset, DatasetStatus
from app.schemas.user import SellerProfile

router = APIRouter(prefix="/sellers", tags=["Sellers"])


@router.get("/{seller_id}", response_model=SellerProfile)
def get_seller_profile(seller_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == seller_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Seller not found")

    datasets = (
        db.query(Dataset)
        .filter(Dataset.seller_id == seller_id, Dataset.status == DatasetStatus.PUBLISHED)
        .order_by(Dataset.published_at.desc())
        .all()
    )

    scores = [d.quality_score for d in datasets if d.quality_score is not None]
    ratings = [d.average_rating for d in datasets if d.average_rating is not None]
    total_sales = sum((d.download_count or 0) for d in datasets)

    return SellerProfile(
        id=user.id,
        full_name=user.full_name,
        organization=user.organization,
        role=user.role,
        is_premium=user.is_premium,
        bio=user.bio,
        website=user.website,
        created_at=user.created_at,
        dataset_count=len(datasets),
        avg_quality_score=round(sum(scores) / len(scores), 1) if scores else None,
        total_sales=total_sales,
        avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        # pydantic coerces each ORM Dataset to DatasetPublic via from_attributes.
        datasets=datasets,
    )
