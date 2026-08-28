"""User accounts: password hashing, JWT issuance/verification, refresh-
token rotation. Plain functions over the DB session, same shape as every
other service in this codebase — no framework (e.g. fastapi-users) sits
between this and app/api/v1/auth.py.

Password hashing is Argon2 (OWASP's current default recommendation,
sidesteps bcrypt's 72-byte input truncation). JWTs are signed with
settings.jwt_secret (HS256) and carry only `sub` (user id) + `exp` — no
extra claims worth trusting client-side, since app/api/v1/auth.py's
`/auth/me` is what actually calls out the verified user (see
app/core/security.py's get_current_user for the flip side of this).
"""

import datetime as dt
import hashlib
import secrets

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppUser, RefreshToken

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"

# Verified against when there is no real hash to check, so that a login
# attempt for an address we've never seen costs the same ~60ms of Argon2 as
# one for a registered address. Without it the `or` in authenticate_user
# short-circuits and an unknown email returns in ~1ms — a timing oracle that
# hands back exactly the account enumeration the identical error message in
# app/api/v1/auth.py exists to prevent. Computed once at import; the value
# is never used for anything but burning the same amount of CPU.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(raw_password: str) -> str:
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str | None) -> bool:
    """False, never an exception, for anything that isn't a matching hash.

    `hashed_password` is None for a Google-only account (see AppUser). That
    case has to be handled here rather than at the call site because
    PasswordHasher.verify(None, ...) raises AttributeError while decoding
    the hash — before argon2 runs at all, so no argon2 exception class
    covers it, and the caller would get a 500 where it wanted a clean
    "wrong credentials".
    """
    if not hashed_password:
        return False
    try:
        return _hasher.verify(hashed_password, raw_password)
    except VerifyMismatchError:
        return False


def create_user(db: Session, email: str, password: str) -> AppUser | None:
    """None on a duplicate email — the caller (app/api/v1/auth.py) turns
    that into the actual HTTP error; this layer just reports "didn't
    happen," matching how the rest of this codebase's services signal
    "nothing to give back" (e.g. get_sector_pe_for_industry)."""
    email = email.strip().lower()
    if db.query(AppUser).filter_by(email=email).one_or_none() is not None:
        return None
    user = AppUser(email=email, hashed_password=hash_password(password))
    db.add(user)
    db.flush()
    return user


def authenticate_user(db: Session, email: str, password: str) -> AppUser | None:
    """None for an unknown email, a wrong password, or a Google-only account
    with no password set — the caller cannot tell which, and neither can a
    stopwatch: every path runs exactly one Argon2 verification."""
    user = db.query(AppUser).filter_by(email=email.strip().lower()).one_or_none()
    stored = user.hashed_password if user is not None else None
    matched = verify_password(password, stored or _DUMMY_HASH)
    if user is None or not stored or not matched:
        return None
    return user


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _issue_access_token(user_id: int) -> str:
    settings = get_settings()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=settings.access_token_ttl_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at}, settings.jwt_secret, algorithm=JWT_ALGORITHM
    )


def _issue_refresh_token(db: Session, user_id: int) -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.refresh_token_ttl_days)
    db.add(
        RefreshToken(
            user_id=user_id, token_hash=_hash_token(raw_token), expires_at=expires_at
        )
    )
    db.flush()
    return raw_token


def issue_tokens(db: Session, user: AppUser) -> tuple[str, str]:
    """Returns (access_token, refresh_token) — the raw JWT/token strings,
    never persisted in that form (the refresh token is stored hashed;
    the access token is never stored at all, verified by signature
    instead)."""
    return _issue_access_token(user.id), _issue_refresh_token(db, user.id)


def decode_access_token(token: str) -> int | None:
    """The user id from a valid, unexpired access token, or None — signature
    and expiry are both checked by jwt.decode itself (PyJWT raises on a bad
    signature and, separately, on an expired `exp`; both are caught here
    since the caller only needs "valid or not")."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


def _valid_refresh_token_row(db: Session, raw_token: str) -> RefreshToken | None:
    row = db.query(RefreshToken).filter_by(token_hash=_hash_token(raw_token)).one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=dt.UTC)
    if expires_at <= dt.datetime.now(dt.UTC):
        return None
    return row


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> tuple[str, str] | None:
    """Verifies `raw_refresh_token`, revokes it, and issues a fresh
    (access, refresh) pair — rotation on every use, so a refresh token is
    only ever valid for one hop before it's dead, win or lose."""
    row = _valid_refresh_token_row(db, raw_refresh_token)
    if row is None:
        return None
    row.revoked_at = dt.datetime.now(dt.UTC)
    db.flush()
    user = db.get(AppUser, row.user_id)
    assert user is not None  # FK guarantees this; the row can't outlive its user
    return issue_tokens(db, user)


def revoke_refresh_token(db: Session, raw_refresh_token: str) -> None:
    """Logout. Silently a no-op for an already-invalid token — the caller
    (a logout request) only cares that the token is dead afterward, not
    whether it already was."""
    row = _valid_refresh_token_row(db, raw_refresh_token)
    if row is None:
        return
    row.revoked_at = dt.datetime.now(dt.UTC)
    db.flush()


def revoke_all_refresh_tokens(db: Session, user_id: int) -> int:
    """Kills every live session for a user. Returns how many were revoked.

    Called on a password reset, and on a Google link that supersedes an
    unproven password. The threat is concrete: someone who registered an
    address they don't own — registration alone proves nothing — holds a
    30-day refresh token, and without this they keep it straight through
    the real owner's recovery.
    """
    revoked = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": dt.datetime.now(dt.UTC)}, synchronize_session=False)
    )
    db.flush()
    return int(revoked)


def set_password(db: Session, user: AppUser, new_password: str) -> None:
    """Also marks the address verified, if it wasn't.

    Setting a password through an emailed code proves control of the inbox
    — the same proof /verify-email/confirm demands — so leaving the account
    unverified afterwards would gate a user who just demonstrated exactly
    what the gate asks for, with no way to understand why.
    """
    user.hashed_password = hash_password(new_password)
    if user.email_verified_at is None:
        user.email_verified_at = dt.datetime.now(dt.UTC)
    db.flush()
