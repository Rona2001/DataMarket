from datetime import datetime, timedelta
from jose import jwt
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.user import UserRegister
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.core.brevo import send_email

RESET_TOKEN_EXPIRE_MINUTES = 30


def register_user(db: Session, data: UserRegister) -> User:
    """Create a new user. Raises 409 if email already taken."""
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        organization=data.organization,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_user(db: Session, email: str, password: str) -> dict:
    """Authenticate user and return JWT tokens."""
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    # Update last login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def request_password_reset(db: Session, email: str) -> None:
    """
    Email a password-reset link. Always succeeds from the caller's point of
    view — never reveals whether the email has an account.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        return

    # Single-use by construction: the token embeds a fingerprint of the
    # CURRENT password hash, so it stops validating once the password changes.
    payload = {
        "sub": str(user.id),
        "type": "reset",
        "pwd": user.hashed_password[-12:],
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    link = f"{settings.FRONTEND_URL}/auth/reset/{token}"

    send_email(
        to_email=user.email,
        to_name=user.full_name,
        subject="Reset your DA/TRUST password",
        html=(
            f"<p>Hi {user.full_name},</p>"
            f"<p>Someone (hopefully you) asked to reset the password for this account.</p>"
            f'<p><a href="{link}">Choose a new password</a> — the link is valid for '
            f"{RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>"
            f"<p>If this wasn't you, you can safely ignore this email.</p>"
            f"<p>— The DA/TRUST team</p>"
        ),
    )


def reset_password(db: Session, token: str, new_password: str) -> None:
    """Set a new password from a valid, unexpired, unused reset token."""
    payload = decode_token(token)
    if payload.get("type") != "reset":
        raise HTTPException(status_code=401, detail="Invalid reset link")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid reset link")
    if payload.get("pwd") != user.hashed_password[-12:]:
        raise HTTPException(status_code=401, detail="This reset link has already been used")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user.hashed_password = hash_password(new_password)
    db.commit()


def refresh_access_token(db: Session, refresh_token: str) -> dict:
    """Issue a new access token from a valid refresh token."""
    payload = decode_token(refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    new_access_token = create_access_token(subject=str(user.id))
    return {
        "access_token": new_access_token,
        "refresh_token": refresh_token,   # reuse same refresh token
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
