"""Account endpoints (Build_plan.md §O, P1). Bare JSON responses, not the
{data, meta} envelope companies.py/opportunities.py use elsewhere — that
envelope's meta.source/meta.confidence are about market-data provenance,
which doesn't apply here; the real precedent for an action endpoint is
admin.py's POST /admin/upstox/token, which also returns a plain dict.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models import AppUser
from app.db.session import get_db
from app.services.alerts import unread_count
from app.services.auth import (
    authenticate_user,
    create_user,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    # Carried here rather than on its own endpoint: the frontend's
    # AppHeader already awaits this payload on every page render, so the
    # bell's count costs zero extra round trips. A dedicated count
    # endpoint would double the Next->FastAPI hops per page. /me exists to
    # answer "what does this session need to render the chrome", and the
    # bell is chrome.
    unread_alert_count: int = 0


def _min_password_length_check(password: str) -> None:
    # A floor, not real strength policy — this is a personal/local
    # deployment (Build_plan.md §O has no mention of a password-strength
    # requirement), so this just rules out the obviously-too-short case
    # rather than pulling in a full policy engine.
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    _min_password_length_check(payload.password)
    user = create_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")
    access_token, refresh_token = issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        # Deliberately identical whether the email doesn't exist or the
        # password is wrong — distinguishing the two would let a caller
        # enumerate registered emails (Build_plan.md §P).
        raise HTTPException(status_code=401, detail="incorrect email or password")
    access_token, refresh_token = issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    rotated = rotate_refresh_token(db, payload.refresh_token)
    if rotated is None:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token")
    access_token, refresh_token = rotated
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    revoke_refresh_token(db, payload.refresh_token)
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
def me(
    current_user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        unread_alert_count=unread_count(db, current_user.id),
    )
