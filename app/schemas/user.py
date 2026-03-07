from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.user import UserRole


# ── Registration ──────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.BUYER
    organization: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


# ── Login ─────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ── User responses ────────────────────────────────────────────────────────────

class UserPublic(BaseModel):
    """Minimal public profile — safe to expose to other users."""
    id: UUID
    full_name: str
    organization: Optional[str]
    role: UserRole
    is_premium: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserMe(BaseModel):
    """Full profile for the authenticated user themselves."""
    id: UUID
    email: str
    full_name: str
    organization: Optional[str]
    role: UserRole
    is_active: bool
    is_verified: bool
    is_premium: bool
    bio: Optional[str]
    website: Optional[str]
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    organization: Optional[str] = None
    bio: Optional[str] = None
    website: Optional[str] = None
    role: Optional[UserRole] = None
