"""Account endpoints (Build_plan.md §O, P1). Bare JSON responses, not the
{data, meta} envelope companies.py/opportunities.py use elsewhere — that
envelope's meta.source/meta.confidence are about market-data provenance,
which doesn't apply here; the real precedent for an action endpoint is
admin.py's POST /admin/upstox/token, which also returns a plain dict.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.rate_limit import is_allowed, rate_limited
from app.core.security import get_current_user
from app.db.models import AppUser
from app.db.session import get_db
from app.providers.auth.google_oauth import (
    build_authorize_url,
    exchange_code,
)
from app.providers.auth.google_oauth import is_configured as google_is_configured
from app.providers.errors import ProviderError
from app.services.alerts import unread_count
from app.services.auth import (
    authenticate_user,
    create_user,
    issue_tokens,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    set_password,
)
from app.services.auth_codes import (
    CodeInvalid,
    CodeThrottled,
    consume_code,
    mark_email_verified,
    send_code,
)
from app.services.google_auth import link_or_create_user

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


class VerifyCodeRequest(BaseModel):
    code: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class GoogleCallbackRequest(BaseModel):
    code: str


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str
    new_password: str


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
    # Same "AppHeader already awaits this" argument as the bell count above:
    # the verify-your-email banner and the Google-account-has-no-password
    # case are both chrome, and both are answerable from the row /me has
    # already loaded. Booleans rather than the raw timestamp/hash — the
    # frontend has no business with either value, only with the two
    # questions they answer.
    email_verified: bool = False
    has_password: bool = True


def _min_password_length_check(password: str) -> None:
    # A floor, not real strength policy — this is a personal/local
    # deployment (Build_plan.md §O has no mention of a password-strength
    # requirement), so this just rules out the obviously-too-short case
    # rather than pulling in a full policy engine.
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")


@router.post(
    "/register", response_model=TokenResponse, dependencies=[rate_limited("auth_register")]
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    _min_password_length_check(payload.password)
    user = create_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")
    access_token, refresh_token = issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse, dependencies=[rate_limited("auth_login")])
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
        email_verified=current_user.email_verified_at is not None,
        has_password=current_user.hashed_password is not None,
    )


# Every failure mode of a code check collapses to this one string. "expired"
# and "wrong" are distinguishable answers only if you know a code was issued
# for that address — which is itself a statement about whether the address is
# registered, and the whole point of the identical login error above is not
# to make those statements.
_BAD_CODE = "that code is invalid or has expired"

# The frontend mints state with crypto.randomUUID(); this is deliberately a
# little wider than that, but still narrow enough that nothing surprising
# can reach a URL we hand to a browser.
_STATE_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")


@router.post("/verify-email/send")
def send_verification_email(
    current_user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    """Send (or resend) the address-verification code.

    429 is safe to return here, unlike on the password-reset request: this
    endpoint is authenticated, so the caller already knows the account
    exists and the status leaks nothing.
    """
    if current_user.email_verified_at is not None:
        return {"status": "already_verified"}
    try:
        send_code(db, current_user, "verify_email")
    except CodeThrottled as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"status": "sent"}


@router.post("/verify-email/confirm")
def confirm_verification_email(
    payload: VerifyCodeRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if current_user.email_verified_at is not None:
        return {"status": "already_verified"}
    try:
        consume_code(db, current_user, "verify_email", payload.code.strip())
    except CodeInvalid as error:
        raise HTTPException(status_code=400, detail=_BAD_CODE) from error
    mark_email_verified(db, current_user)
    return {"status": "verified"}


@router.post("/password-reset/request")
def request_password_reset(
    request: Request, payload: PasswordResetRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Always 200, whatever happens.

    Unknown address, throttled, provider down — all identical, because any
    other answer states whether that address has an account. Note in
    particular that a throttle here must NOT return 429 the way
    /verify-email/send does: that endpoint is authenticated so the caller
    already knows the account exists, while this one is open to anyone.
    That's why this checks the "password_reset_request" limiter manually
    via is_allowed() (app/core/rate_limit.py) rather than the raising
    Depends(rate_limited(...)) every other tier-limited route uses — this
    is the one route where tripping the limit must look identical to not
    tripping it, addressing the aggregate-spray gap the per-address
    auth_codes.py throttle alone doesn't cover (that one bounds sends to
    ONE address; this bounds how many DIFFERENT addresses one caller can
    spray, each of which would otherwise burn a real outbound email).

    The residual side channel is timing — a registered address pays for an
    outbound email, an unregistered one returns immediately. Left as-is
    rather than padded, because POST /auth/register still answers 409 for a
    taken address, which leaks the same fact outright and with no
    measurement required. Closing that is the prerequisite; padding this
    first would be theatre.
    """
    user = (
        db.query(AppUser).filter_by(email=payload.email.strip().lower()).one_or_none()
    )
    if user is not None and is_allowed("password_reset_request", request):
        try:
            send_code(db, user, "password_reset")
        except (CodeThrottled, ProviderError):
            pass
    return {"status": "ok"}


@router.post("/password-reset/confirm", response_model=TokenResponse)
def confirm_password_reset(
    payload: PasswordResetConfirm, db: Session = Depends(get_db)
) -> TokenResponse:
    """Sets the new password and returns a fresh session.

    Allowed even for a Google-only account with no password. Refusing would
    have to happen here, where the refusal is distinguishable from a bad
    code and therefore leaks; and it isn't a downgrade anyway, since a
    Google account's security already rests on control of that inbox.
    """
    _min_password_length_check(payload.new_password)
    user = (
        db.query(AppUser).filter_by(email=payload.email.strip().lower()).one_or_none()
    )
    if user is None:
        # Byte-identical to a wrong code — see _BAD_CODE.
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    try:
        consume_code(db, user, "password_reset", payload.code.strip())
    except CodeInvalid as error:
        raise HTTPException(status_code=400, detail=_BAD_CODE) from error

    # Revoke BEFORE issuing: the other order would kill the pair just
    # minted and sign the user out of the recovery they just completed.
    revoke_all_refresh_tokens(db, user.id)
    set_password(db, user, payload.new_password)
    access_token, refresh_token = issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/providers")
def available_providers() -> dict[str, bool]:
    """Which third-party sign-ins are configured on this deployment.

    Exists so the login page can hide a Google button that would only fail.
    A runtime answer rather than a NEXT_PUBLIC_* build-time variable: those
    are inlined into the bundle by frontend/Dockerfile, so configuring
    Google would otherwise require a frontend rebuild.
    """
    return {"google": google_is_configured()}


@router.get("/google/authorize-url")
def google_authorize_url(state: str) -> dict[str, str]:
    """Where to send the browser to start the Google flow.

    `state` is minted and stored in a cookie by the frontend route handler;
    this only echoes it into the URL. Validated against a strict charset
    anyway — it is caller-supplied and ends up in a URL we hand to a
    browser.
    """
    if not _STATE_PATTERN.fullmatch(state):
        raise HTTPException(status_code=400, detail="invalid state")
    try:
        return {"url": build_authorize_url(state)}
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/google/callback", response_model=TokenResponse)
def google_callback(
    payload: GoogleCallbackRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    """Exchange the authorization code and sign the user in.

    CSRF protection (the `state` round trip) lives in the frontend route
    handler, which is where the cookie holding it can be read.
    """
    try:
        identity = exchange_code(payload.code)
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    user = link_or_create_user(db, identity)
    access_token, refresh_token = issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)
