"""
Dataset Request Board routes (spec §10).

Buyer (auth):
  POST   /requests                 — create a draft from the survey
  GET    /requests/mine            — my requests
  PATCH  /requests/{id}            — edit while draft/pending/rejected
  POST   /requests/{id}/submit     — submit for moderation
  POST   /requests/{id}/fulfill    — mark satisfied

Public:
  GET    /requests                 — browse the published board (filters)
  GET    /requests/{id}            — request detail

Seller (auth):
  POST   /requests/{id}/respond    — structured 'I have this'

Admin:
  GET    /admin/requests/pending   — moderation queue
  POST   /admin/requests/{id}/approve
  POST   /admin/requests/{id}/reject
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user, get_current_active_seller, get_current_admin
from app.core import brevo
from app.core.config import settings
from app.services.alert_service import send_request_alerts
from app.schemas.request import (
    RequestCreate, RequestUpdate, RequestPublic, RequestList,
    RequestResponseCreate, RequestResponsePublic,
)
from app.services import request_service

router = APIRouter(tags=["Request Board"])


# ── Buyer ───────────────────────────────────────────────────────────────────────

@router.post("/requests", response_model=RequestPublic, status_code=201)
def create_request(
    data: RequestCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a draft request from the survey answers. Returns the generated card to edit."""
    return request_service.create_request(db, user, data)


@router.get("/requests", response_model=RequestList)
def browse_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: Optional[str] = None,
    data_type: Optional[str] = None,
    intended_use: Optional[str] = None,
    budget_range: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Public board — only published requests."""
    return request_service.list_public(db, page, page_size, domain, data_type, intended_use, budget_range)


@router.get("/requests/mine", response_model=List[RequestPublic])
def my_requests(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return request_service.list_mine(db, user)


@router.get("/requests/{request_id}", response_model=RequestPublic)
def get_request(request_id: str, db: Session = Depends(get_db)):
    return request_service.get_public_request(db, request_id)


@router.patch("/requests/{request_id}", response_model=RequestPublic)
def update_request(
    request_id: str,
    updates: RequestUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return request_service.update_request(db, request_id, user, updates)


@router.post("/requests/{request_id}/submit", response_model=RequestPublic)
def submit_request(request_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return request_service.submit_request(db, request_id, user)


@router.post("/requests/{request_id}/fulfill", response_model=RequestPublic)
def fulfill_request(request_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return request_service.fulfill_request(db, request_id, user)


# ── Seller responses ─────────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/respond", response_model=RequestResponsePublic, status_code=201)
def respond_to_request(
    request_id: str,
    data: RequestResponseCreate,
    background_tasks: BackgroundTasks,
    seller=Depends(get_current_active_seller),
    db: Session = Depends(get_db),
):
    """Seller signals 'I have this' — structured, platform-mediated (no open messaging)."""
    resp = request_service.respond_to_request(db, request_id, seller, data)

    # Notify the requester (best-effort, non-blocking).
    req = resp.request
    requester = req.requester
    if requester and requester.email:
        link = f"{settings.FRONTEND_URL.rstrip('/')}/requests/{req.id}"
        background_tasks.add_task(
            brevo.send_email,
            requester.email,
            "A seller responded to your dataset request",
            f"<p>Good news — a seller says they can provide data matching your request "
            f"<strong>{req.title}</strong>.</p>"
            f"<p><a href=\"{link}\">View the response on datrust</a>.</p>",
            requester.full_name,
        )

    return resp


# ── Admin moderation ──────────────────────────────────────────────────────────

@router.get("/admin/requests/pending", response_model=List[RequestPublic])
def list_pending_requests(admin=Depends(get_current_admin), db: Session = Depends(get_db)):
    return request_service.list_pending(db)


@router.post("/admin/requests/{request_id}/approve", response_model=RequestPublic)
def approve_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    req = request_service.approve_request(db, request_id)
    # Notify sellers following this category (spec §11, closes the §10 gap).
    background_tasks.add_task(send_request_alerts, str(req.id))
    return req


@router.post("/admin/requests/{request_id}/reject", response_model=RequestPublic)
def reject_request(request_id: str, admin=Depends(get_current_admin), db: Session = Depends(get_db)):
    return request_service.reject_request(db, request_id)
