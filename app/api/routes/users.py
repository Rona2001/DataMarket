from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.schemas.user import UserMe, UserPublic, UserUpdate
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserMe)
def get_my_profile(current_user=Depends(get_current_user)):
    """Get the authenticated user's full profile."""
    return current_user


@router.patch("/me", response_model=UserMe)
def update_my_profile(
    updates: UserUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's profile."""
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/{user_id}", response_model=UserPublic)
def get_user_profile(user_id: UUID, db: Session = Depends(get_db)):
    """Get a public profile by user ID (for viewing seller profiles)."""
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
