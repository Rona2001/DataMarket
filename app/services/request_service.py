"""
Dataset Request Board service (spec §10).

Lifecycle: draft → pending_review → published → fulfilled
                              ↘ rejected (moderation)

The requester creates a draft from the survey, can edit it, then submits for
moderation. An admin approves it onto the public board. Sellers respond with a
structured 'I have this'. Aggregate answers form the internal demand map.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dataset_request import DatasetRequest, RequestResponse, RequestStatus
from app.models.user import User
from app.schemas.request import RequestCreate, RequestUpdate, RequestResponseCreate


# ── Human labels for the normalised title ──────────────────────────────────────

VOLUME_LABELS = {"<10k": "<10k lignes", "10k-1M": "10k–1M lignes", ">1M": ">1M lignes"}
USE_LABELS = {"academic": "usage académique", "prototyping": "prototypage", "commercial": "usage commercial"}
BUDGET_LABELS = {"0-50": "0–50 €", "50-300": "50–300 €", "300-2000": "300–2 000 €", "2000+": "2 000 €+"}


def build_title(domain: str, volume: str, intended_use: str, budget_range: str) -> str:
    """Normalised card title, e.g. 'Corpus NLP français · <1M lignes · usage commercial · 300–2 000 €'."""
    parts = [
        domain.strip() if domain else None,
        VOLUME_LABELS.get(volume),
        USE_LABELS.get(intended_use),
        BUDGET_LABELS.get(budget_range),
    ]
    return " · ".join(p for p in parts if p)


# ── Create / edit / submit ──────────────────────────────────────────────────────

def create_request(db: Session, user: User, data: RequestCreate) -> DatasetRequest:
    req = DatasetRequest(
        requester_id=user.id,
        domain=data.domain,
        data_types=data.data_types or [],
        volume=data.volume,
        intended_use=data.intended_use,
        rgpd_constraint=data.rgpd_constraint,
        budget_range=data.budget_range,
        deadline=data.deadline,
        free_text=data.free_text,
        title=build_title(data.domain, data.volume, data.intended_use, data.budget_range),
        status=RequestStatus.DRAFT,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def update_request(db: Session, request_id: str, user: User, updates: RequestUpdate) -> DatasetRequest:
    req = _get_owned(db, request_id, user)
    if req.status not in (RequestStatus.DRAFT, RequestStatus.PENDING_REVIEW, RequestStatus.REJECTED):
        raise HTTPException(status_code=400, detail=f"A '{req.status.value}' request can no longer be edited.")

    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(req, field, value)

    # Recompute the normalised title from whatever the fields are now.
    req.title = build_title(req.domain, req.volume, req.intended_use, req.budget_range)
    db.commit()
    db.refresh(req)
    return req


def submit_request(db: Session, request_id: str, user: User) -> DatasetRequest:
    req = _get_owned(db, request_id, user)
    if req.status not in (RequestStatus.DRAFT, RequestStatus.REJECTED):
        raise HTTPException(status_code=400, detail="Only a draft or rejected request can be submitted.")
    req.status = RequestStatus.PENDING_REVIEW
    db.commit()
    db.refresh(req)
    return req


def fulfill_request(db: Session, request_id: str, user: User) -> DatasetRequest:
    req = _get_owned(db, request_id, user)
    req.status = RequestStatus.FULFILLED
    db.commit()
    db.refresh(req)
    return req


# ── Public board ────────────────────────────────────────────────────────────────

def list_public(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    domain: Optional[str] = None,
    data_type: Optional[str] = None,
    intended_use: Optional[str] = None,
    budget_range: Optional[str] = None,
) -> dict:
    query = db.query(DatasetRequest).filter(DatasetRequest.status == RequestStatus.PUBLISHED)

    if domain:
        query = query.filter(DatasetRequest.domain == domain)
    if intended_use:
        query = query.filter(DatasetRequest.intended_use == intended_use)
    if budget_range:
        query = query.filter(DatasetRequest.budget_range == budget_range)
    if data_type:
        # data_types is a JSON array; filter in Python after fetch to stay portable.
        pass

    total = query.count()
    items = (
        query.order_by(DatasetRequest.published_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    if data_type:
        items = [r for r in items if data_type in (r.data_types or [])]
        total = len(items)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
    }


def get_public_request(db: Session, request_id: str) -> DatasetRequest:
    req = db.query(DatasetRequest).filter(DatasetRequest.id == request_id).first()
    if not req or req.status not in (RequestStatus.PUBLISHED, RequestStatus.FULFILLED):
        raise HTTPException(status_code=404, detail="Request not found")
    return req


def list_mine(db: Session, user: User) -> list:
    return (
        db.query(DatasetRequest)
        .filter(DatasetRequest.requester_id == user.id)
        .order_by(DatasetRequest.created_at.desc())
        .all()
    )


# ── Seller responses ('I have this') ─────────────────────────────────────────────

def respond_to_request(
    db: Session, request_id: str, seller: User, data: RequestResponseCreate
) -> RequestResponse:
    req = db.query(DatasetRequest).filter(DatasetRequest.id == request_id).first()
    if not req or req.status != RequestStatus.PUBLISHED:
        raise HTTPException(status_code=404, detail="Request not found or not open")
    if str(req.requester_id) == str(seller.id):
        raise HTTPException(status_code=400, detail="You can't respond to your own request.")

    existing = (
        db.query(RequestResponse)
        .filter(RequestResponse.request_id == request_id, RequestResponse.seller_id == seller.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="You've already responded to this request.")

    resp = RequestResponse(
        request_id=req.id,
        seller_id=seller.id,
        dataset_id=data.dataset_id,
        message=data.message,
    )
    db.add(resp)
    db.commit()
    db.refresh(resp)
    return resp


# ── Admin moderation ──────────────────────────────────────────────────────────

def list_pending(db: Session) -> list:
    return (
        db.query(DatasetRequest)
        .filter(DatasetRequest.status == RequestStatus.PENDING_REVIEW)
        .order_by(DatasetRequest.created_at.asc())
        .all()
    )


def approve_request(db: Session, request_id: str) -> DatasetRequest:
    req = _get_or_404(db, request_id)
    req.status = RequestStatus.PUBLISHED
    req.published_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return req


def reject_request(db: Session, request_id: str) -> DatasetRequest:
    req = _get_or_404(db, request_id)
    req.status = RequestStatus.REJECTED
    db.commit()
    db.refresh(req)
    return req


# ── Private helpers ─────────────────────────────────────────────────────────────

def _get_or_404(db: Session, request_id: str) -> DatasetRequest:
    req = db.query(DatasetRequest).filter(DatasetRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


def _get_owned(db: Session, request_id: str, user: User) -> DatasetRequest:
    req = _get_or_404(db, request_id)
    if str(req.requester_id) != str(user.id):
        raise HTTPException(status_code=403, detail="You don't own this request")
    return req
