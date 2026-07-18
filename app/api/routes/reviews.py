"""
Reviews & Ratings routes (spec §13).

Public:
  GET  /datasets/{id}/reviews              — list reviews for a dataset

Buyer (auth):
  GET  /datasets/{id}/reviews/eligibility  — can I review this dataset?
  POST /datasets/{id}/reviews              — leave a review (gated on completed purchase)

Seller (auth):
  POST /reviews/{review_id}/respond        — respond once to a review
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller
from app.schemas.review import ReviewCreate, ReviewPublic, ReviewRespond, ReviewEligibility
from app.services import review_service

router = APIRouter(tags=["Reviews"])


@router.get("/datasets/{dataset_id}/reviews", response_model=List[ReviewPublic])
def list_reviews(dataset_id: str, db: Session = Depends(get_db)):
    return review_service.list_reviews(db, dataset_id)


@router.get("/datasets/{dataset_id}/reviews/eligibility", response_model=ReviewEligibility)
def review_eligibility(dataset_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return review_service.get_eligibility(db, user, dataset_id)


@router.post("/datasets/{dataset_id}/reviews", response_model=ReviewPublic, status_code=201)
def create_review(
    dataset_id: str,
    data: ReviewCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return review_service.create_review(db, user, dataset_id, data)


@router.post("/reviews/{review_id}/respond", response_model=ReviewPublic)
def respond_to_review(
    review_id: str,
    data: ReviewRespond,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    return review_service.respond_to_review(db, seller, review_id, data.response)
