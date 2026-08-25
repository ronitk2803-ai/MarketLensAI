from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppUser
from app.db.session import get_db
from app.services.auth import decode_access_token


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate for admin-only endpoints (Build_plan.md §P: admin endpoints authn+authz gated).

    P0 has no user auth system yet, so this is a shared-secret header check
    against `ADMIN_TOKEN` rather than a full auth dependency.
    """
    settings = get_settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="unauthorized")


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AppUser:
    """P1's real auth gate: `Authorization: Bearer <access token>`. Raises
    401 for anything wrong with it (missing header, bad scheme, bad
    signature, expired, or a user id that no longer exists) — the caller
    never needs to distinguish which, since the response to all of them is
    the same "sign in again."
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    user_id = decode_access_token(authorization.removeprefix("Bearer "))
    if user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
