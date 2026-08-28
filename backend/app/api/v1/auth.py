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
        email_verified=current_user.email_verified_at is not None,
        has_password=current_user.hashed_password is not None,
    )


# Every failure mode of a code check collapses to this one string. "expired"
# and "wrong" are distinguishable answers only if you know a code was issued
# for that address — which is itself a statement about whether the address is
# registered, and the whole point of the identical login error above is not
# to make those statements.
_BAD_CODE = "that code is invalid or has expired"


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
    payload: PasswordResetRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Always 200, whatever happens.

    Unknown address, throttled, provider down — all identical, because any
    other answer states whether that address has an account. Note in
    particular that a throttle here must NOT return 429 the way
    /verify-email/send does: that endpoint is authenticated so the caller
    already knows the account exists, while this one is open to anyone.

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
    if user is not None:
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
