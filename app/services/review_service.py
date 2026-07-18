"""
Reviews & Ratings service (spec §13).

Gating rules:
  - Only a buyer with a COMPLETED purchase of the dataset can review it.
  - One review per purchase (a buyer who bought twice can review twice).
  - The seller may respond to a review once.

Every write recomputes Dataset.average_rating so the seller profile (§12) and
dataset detail page stay in sync.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.review import Review
from app.models.purchase import Purchase, PurchaseStatus
from app.models.dataset import Dataset
from app.models.user import User
from app.schemas.review import ReviewCreate


def _first_name(full_name: str | None) -> str:
    return (full_name or "A buyer").strip().split(" ")[0]


def _reviewable_purchase(db: Session, buyer: User, dataset_id: str) -> Purchase | None:
    """A completed purchase by this buyer for this dataset that hasn't been reviewed yet."""
    completed = (
        db.query(Purchase)
        .filter(
            Purchase.buyer_id == buyer.id,
            Purchase.dataset_id == dataset_id,
            Purchase.status == PurchaseStatus.COMPLETED,
        )
        .order_by(Purchase.completed_at.asc())
        .all()
    )
    for p in completed:
        already = db.query(Review).filter(Review.purchase_id == p.id).first()
        if not already:
            return p
    return None


def get_eligibility(db: Session, buyer: User, dataset_id: str) -> dict:
    if _reviewable_purchase(db, buyer, dataset_id):
        return {"can_review": True, "reason": "You purchased this dataset — share your experience."}
    # Distinguish "never bought" from "already reviewed" for a clearer message.
    has_completed = (
        db.query(Purchase)
        .filter(
            Purchase.buyer_id == buyer.id,
            Purchase.dataset_id == dataset_id,
            Purchase.status == PurchaseStatus.COMPLETED,
        )
        .first()
    )
    if has_completed:
        return {"can_review": False, "reason": "You've already reviewed this purchase."}
    return {"can_review": False, "reason": "Only buyers of this dataset can review it."}


def create_review(db: Session, buyer: User, dataset_id: str, data: ReviewCreate) -> Review:
    purchase = _reviewable_purchase(db, buyer, dataset_id)
    if not purchase:
        raise HTTPException(
            status_code=403,
            detail="You can only review a dataset you've purchased, once per purchase.",
        )

    review = Review(
        dataset_id=dataset_id,
        buyer_id=buyer.id,
        purchase_id=purchase.id,
        rating=data.rating,
        tags=data.tags or [],
        text=data.text,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    _recompute_average(db, dataset_id)

    review.reviewer_name = _first_name(buyer.full_name)
    return review


def list_reviews(db: Session, dataset_id: str) -> list:
    reviews = (
        db.query(Review)
        .filter(Review.dataset_id == dataset_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    for r in reviews:
        r.reviewer_name = _first_name(r.buyer.full_name if r.buyer else None)
    return reviews


def respond_to_review(db: Session, seller: User, review_id: str, response: str) -> Review:
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    dataset = db.query(Dataset).filter(Dataset.id == review.dataset_id).first()
    if not dataset or str(dataset.seller_id) != str(seller.id):
        raise HTTPException(status_code=403, detail="Only the dataset's seller can respond.")
    if review.seller_response:
        raise HTTPException(status_code=409, detail="You've already responded to this review.")

    review.seller_response = response
    review.seller_responded_at = datetime.utcnow()
    db.commit()
    db.refresh(review)
    review.reviewer_name = _first_name(review.buyer.full_name if review.buyer else None)
    return review


def _recompute_average(db: Session, dataset_id: str) -> None:
    ratings = [r.rating for r in db.query(Review).filter(Review.dataset_id == dataset_id).all()]
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset:
        dataset.average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
        db.commit()
