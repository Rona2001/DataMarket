from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import UserRegister, UserMe, TokenResponse, RefreshTokenRequest
from app.services.auth_service import register_user, login_user, refresh_access_token
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


@router.get("/me", response_model=UserMe)
def get_me(current_user=Depends(get_current_user)):
    """
    Return the profile of the currently authenticated user.
    """
    return current_user
