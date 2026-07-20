from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.schemas.user import UserMe, UserPublic, UserUpdate
from app.core.security import get_current_user
from app.core.config import settings
from app.core import storage
from app.models.user import User

router = APIRouter(prefix="/users", tags=["Users"])

# Avatars live in the public samples bucket under a fixed per-user key, so the
# URL is derivable from the user id alone — no DB column needed (create_all
# can't add columns to existing tables).
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB


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


@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    """Upload (or replace) the authenticated user's profile picture."""
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG or WebP images are allowed")
    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 2 MB")
    key = f"avatars/{current_user.id}"
    storage.upload_file(settings.SUPABASE_SAMPLE_BUCKET, key, data, file.content_type)
    return {"avatar_url": storage.get_public_sample_url(key)}


@router.delete("/me/avatar")
def remove_avatar(current_user=Depends(get_current_user)):
    """Remove the authenticated user's profile picture."""
    storage.delete_file(settings.SUPABASE_SAMPLE_BUCKET, f"avatars/{current_user.id}")
    return {"avatar_url": None}


@router.get("/{user_id}", response_model=UserPublic)
def get_user_profile(user_id: UUID, db: Session = Depends(get_db)):
    """Get a public profile by user ID (for viewing seller profiles)."""
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
