from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import (
    UserRegister, UserMe, TokenResponse, RefreshTokenRequest,
    ForgotPasswordRequest, ResetPasswordRequest,
)
from app.services.auth_service import (
    register_user, login_user, refresh_access_token,
    request_password_reset, reset_password,
)
from app.core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserMe, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new account (buyer, seller, or both).
    """
    user = register_user(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Login with email + password. Returns JWT access & refresh tokens.
    Use the access_token as: Authorization: Bearer <token>
    """
    return login_user(db, email=form.username, password=form.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Get a new access token using a refresh token (no re-login needed).
    """
    return refresh_access_token(db, body.refresh_token)


@router.post("/forgot-password", status_code=202)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Email a password-reset link. Responds 202 whether or not the email
    exists, to avoid account enumeration.
    """
    request_password_reset(db, body.email)
    return {"message": "If an account exists for this email, a reset link has been sent."}


@router.post("/reset-password")
def do_reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Set a new password using a token from the reset email."""
    reset_password(db, body.token, body.new_password)
    return {"message": "Password updated — you can now sign in."}


@router.get("/me", response_model=UserMe)
def get_me(current_user=Depends(get_current_user)):
    """
    Return the profile of the currently authenticated user.
    """
    return current_user
