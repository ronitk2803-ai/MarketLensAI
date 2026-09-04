import secrets

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

    `compare_digest`, not `!=`: Python's string equality short-circuits on
    the first differing byte, so the time it takes to reject a guess leaks
    how long its correct prefix was — enough, over many requests, to
    recover the token one byte at a time. This is a single fixed secret
    with no lockout and no rotation story, which is exactly the shape of
    secret that attack is practical against. compare_digest takes the same
    time regardless of where the mismatch falls.
    """
    settings = get_settings()
    if not settings.admin_token or x_admin_token is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not secrets.compare_digest(x_admin_token, settings.admin_token):
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


# The message endpoints return when the account is real but the address
# hasn't been confirmed. Kept as a constant because the frontend surfaces
# `detail` verbatim in several forms, so this string is UI copy.
UNVERIFIED_DETAIL = "verify your email address to save changes"


def get_current_verified_user(
    current_user: AppUser = Depends(get_current_user),
) -> AppUser:
    """`get_current_user` plus a confirmed email address.

    403 rather than 401: the session is perfectly valid, the account just
    isn't allowed to do this yet. A 401 would tell the frontend to send the
    user back to a login screen they are already past.

    Depends on the other dependency rather than re-reading the token, so
    FastAPI's per-request caching means this costs no extra query.

    Worth noting why an old token can't slip past: access tokens carry only
    `sub` and `exp`, so verification status is never in the token and is
    read from the row on every request. Verifying takes effect on the next
    request with the same token, and a token minted before this gate existed
    is evaluated against current state like any other.
    """
    if current_user.email_verified_at is None:
        raise HTTPException(status_code=403, detail=UNVERIFIED_DETAIL)
    return current_user
