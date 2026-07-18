"""
Category Alerts service (spec §11).

Follow management + the background jobs that fire when a dataset is published
or a request goes live. Each send is throttled to at most one email per user
per ALERT_THROTTLE_HOURS to protect sender reputation.
"""
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import brevo
from app.db.session import SessionLocal
from app.models.alert import CategoryFollow, AlertLog
from app.models.user import User, UserRole
from app.models.dataset import Dataset
from app.models.dataset_request import DatasetRequest

logger = logging.getLogger(__name__)


# ── Follow management (request-scoped) ──────────────────────────────────────────

def follow_category(db: Session, user: User, category: str) -> CategoryFollow:
    category = (category or "").strip()
    if not category:
        raise HTTPException(status_code=422, detail="A category is required")

    existing = (
        db.query(CategoryFollow)
        .filter(CategoryFollow.user_id == user.id, CategoryFollow.category == category)
        .first()
    )
    if existing:
        return existing  # idempotent — one-click follow shouldn't error on repeat

    follow = CategoryFollow(user_id=user.id, category=category)
    db.add(follow)
    db.commit()
    db.refresh(follow)
    return follow


def unfollow_category(db: Session, user: User, category: str) -> None:
    follow = (
        db.query(CategoryFollow)
        .filter(CategoryFollow.user_id == user.id, CategoryFollow.category == category)
        .first()
    )
    if follow:
        db.delete(follow)
        db.commit()


def unsubscribe_by_token(db: Session, token: str) -> str:
    """RGPD one-click unsubscribe from an email link. Returns the category removed."""
    follow = db.query(CategoryFollow).filter(CategoryFollow.unsubscribe_token == token).first()
    if not follow:
        raise HTTPException(status_code=404, detail="This unsubscribe link is invalid or already used.")
    category = follow.category
    db.delete(follow)
    db.commit()
    return category


def list_my_follows(db: Session, user: User) -> list:
    return (
        db.query(CategoryFollow)
        .filter(CategoryFollow.user_id == user.id)
        .order_by(CategoryFollow.created_at.desc())
        .all()
    )


# ── Background senders (open their own session) ─────────────────────────────────

def _recently_alerted(db: Session, user_id) -> bool:
    window = datetime.utcnow() - timedelta(hours=settings.ALERT_THROTTLE_HOURS)
    return (
        db.query(AlertLog)
        .filter(AlertLog.user_id == user_id, AlertLog.sent_at >= window)
        .first()
        is not None
    )


def _unsubscribe_url(follow: CategoryFollow) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/alerts/unsubscribe/{follow.unsubscribe_token}"


def send_dataset_alerts(dataset_id: str) -> None:
    """Background task: notify followers of a newly published dataset's category."""
    db = SessionLocal()
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset or not dataset.category:
            return

        follows = (
            db.query(CategoryFollow)
            .filter(CategoryFollow.category == dataset.category)
            .all()
        )
        link = f"{settings.FRONTEND_URL.rstrip('/')}/dataset/{dataset.id}"
        for follow in follows:
            # Don't notify the seller about their own dataset.
            if str(follow.user_id) == str(dataset.seller_id):
                continue
            if _recently_alerted(db, follow.user_id):
                continue
            user = follow.user
            if not user or not user.email:
                continue
            sent = brevo.send_email(
                user.email,
                f"New {dataset.category} dataset on datrust",
                f"<p>A new verified dataset in <strong>{dataset.category}</strong> was just published: "
                f"<strong>{dataset.title}</strong>.</p>"
                f"<p><a href=\"{link}\">View it on datrust</a>.</p>"
                f"<p style=\"font-size:12px;color:#888\">"
                f"<a href=\"{_unsubscribe_url(follow)}\">Unsubscribe from {dataset.category} alerts</a></p>",
                user.full_name,
            )
            # Log regardless of Brevo config so the throttle behaves consistently.
            db.add(AlertLog(user_id=follow.user_id, kind="dataset", ref_id=str(dataset.id)))
            db.commit()
            logger.info("dataset alert to %s (sent=%s)", user.email, sent)
    finally:
        db.close()


def send_request_alerts(request_id: str) -> None:
    """
    Background task: notify sellers following a category when a matching request
    is published. Closes the piece deferred in §10.
    """
    db = SessionLocal()
    try:
        req = db.query(DatasetRequest).filter(DatasetRequest.id == request_id).first()
        if not req or not req.domain:
            return

        follows = db.query(CategoryFollow).filter(CategoryFollow.category == req.domain).all()
        link = f"{settings.FRONTEND_URL.rstrip('/')}/requests/{req.id}"
        for follow in follows:
            if str(follow.user_id) == str(req.requester_id):
                continue
            user = follow.user
            # Only sellers can act on a request.
            if not user or user.role not in (UserRole.SELLER, UserRole.BOTH, UserRole.ADMIN):
                continue
            if not user.email or _recently_alerted(db, follow.user_id):
                continue
            sent = brevo.send_email(
                user.email,
                f"New {req.domain} data request on datrust",
                f"<p>A buyer is looking for data in <strong>{req.domain}</strong>: "
                f"<strong>{req.title}</strong>.</p>"
                f"<p>If you have a matching dataset, <a href=\"{link}\">respond on datrust</a>.</p>"
                f"<p style=\"font-size:12px;color:#888\">"
                f"<a href=\"{_unsubscribe_url(follow)}\">Unsubscribe from {req.domain} alerts</a></p>",
                user.full_name,
            )
            db.add(AlertLog(user_id=follow.user_id, kind="request", ref_id=str(req.id)))
            db.commit()
            logger.info("request alert to %s (sent=%s)", user.email, sent)
    finally:
        db.close()
