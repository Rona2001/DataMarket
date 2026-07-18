"""
Category Alerts / 'Notify Me' routes (spec §11).

Auth:
  GET    /alerts/mine        — my followed categories
  POST   /alerts/follow      — follow a category
  POST   /alerts/unfollow    — unfollow a category

Public:
  GET    /alerts/unsubscribe/{token}  — RGPD one-click unsubscribe from an email link
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.schemas.alert import FollowInput, FollowPublic
from app.services import alert_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/mine", response_model=List[FollowPublic])
def my_follows(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alert_service.list_my_follows(db, user)


@router.post("/follow", response_model=FollowPublic, status_code=201)
def follow(data: FollowInput, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alert_service.follow_category(db, user, data.category)


@router.post("/unfollow", status_code=204)
def unfollow(data: FollowInput, user=Depends(get_current_user), db: Session = Depends(get_db)):
    alert_service.unfollow_category(db, user, data.category)


@router.get("/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Public — hit from the unsubscribe link in an alert email."""
    category = alert_service.unsubscribe_by_token(db, token)
    return {"unsubscribed": True, "category": category}
