"""Short-lived email codes: issue, throttle, and verify.

Backs two flows that both reduce to "prove you can read this inbox" —
verifying a new account's address, and resetting a forgotten password.

Two things here are easy to get subtly wrong, and both have a live
precedent in this codebase:

1. **The attempt counter and the throttle rows must be committed before the
   error is raised.** app/db/session.py's get_db rolls the whole request
   back on any exception, so a flush-only increment vanishes along with the
   400 it accompanied — and a limit that never persists is not a limit.
   Without it, a 6-digit code is guessable in 10^6 requests. This is the
   same trap, with the same fix, that app/services/company_summary.py
   documents for its provider cooldown.

2. **A code that could not be emailed must be killed, not rolled back.**
   The row is simultaneously the credential and the throttle record, so
   discarding it to avoid an orphan code would also erase the evidence that
   a send was attempted, letting a caller hammer a broken provider. It is
   marked consumed instead: dead as a credential, intact as history.
"""

import datetime as dt
import hashlib
import hmac
import secrets
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppUser, AuthCode
from app.providers.email.resend import ResendEmailProvider
from app.providers.errors import ProviderError

AuthCodePurpose = Literal["verify_email", "password_reset"]

# Long enough to switch to an email client and back, short enough that a
# code left in an inbox isn't a standing credential.
CODE_TTL = dt.timedelta(minutes=10)

# Spacing between sends, and a ceiling per hour. The ceiling is the reason
# an attacker can't use "resend" to spray someone's inbox; the spacing is
# the reason an impatient user can't do it by accident.
RESEND_COOLDOWN = dt.timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 10
SENDS_WINDOW = dt.timedelta(hours=1)

# Guesses allowed against one code before it is retired. With 10^6
# possibilities and a 10-minute life, five guesses is not the binding
# constraint on a legitimate user and is fatal to a guesser.
MAX_ATTEMPTS = 5

_CODE_DIGITS = 6


class CodeThrottled(Exception):
    """Too soon, or too many in the last hour."""


class CodeInvalid(Exception):
    """No live code, expired, wrong, or out of attempts.

    Deliberately one exception for all four: the caller must not be able to
    tell them apart, since "expired" and "wrong" leak whether a code was
    ever issued for that address, which leaks whether the address is
    registered.
    """


def _hash_code(code: str) -> str:
    """HMAC keyed on the app secret, not a bare digest.

    See AuthCode's docstring: 20 bits of entropy behind a plain SHA-256 is
    reversed from a stolen database instantly, and the pepper lives in the
    environment rather than in Postgres. Domain-separated so a code digest
    can never collide with any other HMAC this key is used for.
    """
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, b"auth_code:v1:" + code.encode(), hashlib.sha256).hexdigest()


def _generate_code() -> str:
    # Zero-padded: "042931" is a perfectly valid code, and str() of the same
    # integer would silently produce a 5-character one.
    return f"{secrets.randbelow(10**_CODE_DIGITS):0{_CODE_DIGITS}d}"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _live_code(db: Session, user_id: int, purpose: AuthCodePurpose) -> AuthCode | None:
    return (
        db.query(AuthCode)
        .filter_by(user_id=user_id, purpose=purpose, consumed_at=None)
        .order_by(AuthCode.created_at.desc())
        .first()
    )


def _check_throttle(db: Session, user_id: int, purpose: AuthCodePurpose) -> None:
    now = _now()
    latest = (
        db.query(AuthCode)
        .filter_by(user_id=user_id, purpose=purpose)
        .order_by(AuthCode.created_at.desc())
        .first()
    )
    if latest is not None and now - _aware(latest.created_at) < RESEND_COOLDOWN:
        raise CodeThrottled("a code was just sent — wait a minute before asking for another")

    recent = (
        db.query(func.count(AuthCode.id))
        .filter(
            AuthCode.user_id == user_id,
            AuthCode.purpose == purpose,
            AuthCode.created_at >= now - SENDS_WINDOW,
        )
        .scalar()
        or 0
    )
    if recent >= MAX_SENDS_PER_HOUR:
        raise CodeThrottled("too many codes requested — try again later")


_SUBJECTS: dict[str, str] = {
    "verify_email": "Verify your MarketLens AI email address",
    "password_reset": "Reset your MarketLens AI password",
}


def _body(purpose: AuthCodePurpose, code: str) -> str:
    minutes = int(CODE_TTL.total_seconds() // 60)
    if purpose == "password_reset":
        lead = "Someone asked to reset the password on your MarketLens AI account."
        tail = "If that wasn't you, ignore this email — your password hasn't changed."
    else:
        lead = "Welcome to MarketLens AI. Confirm this is your address:"
        tail = "If you didn't create this account, you can ignore this email."
    return f"{lead}\n\n    {code}\n\nThis code expires in {minutes} minutes.\n\n{tail}\n"


def send_code(db: Session, user: AppUser, purpose: AuthCodePurpose) -> None:
    """Issue a code and email it. Raises CodeThrottled or ProviderError.

    Ordering is deliberate throughout — see the module docstring.
    """
    _check_throttle(db, user.id, purpose)

    # Supersede whatever is outstanding, so one attempt budget guards one
    # code rather than several.
    now = _now()
    for stale in db.query(AuthCode).filter_by(
        user_id=user.id, purpose=purpose, consumed_at=None
    ):
        stale.consumed_at = now
    # Mandatory, not defensive: within a single flush SQLAlchemy emits every
    # INSERT for a mapper before every UPDATE, so the new row would hit the
    # partial unique index while the old one still looks live. autoflush is
    # off, so nothing does this implicitly.
    db.flush()

    code = _generate_code()  # never logged, never returned
    row = AuthCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=_hash_code(code),
        expires_at=now + CODE_TTL,
    )
    db.add(row)
    db.flush()

    settings = get_settings()
    if not settings.resend_api_key:
        raise ProviderError("resend", "RESEND_API_KEY not configured")

    provider = ResendEmailProvider(
        settings.resend_api_key, from_email=settings.resend_from_email
    )
    try:
        provider.send(
            to=user.email,
            subject=_SUBJECTS[purpose],
            text=_body(purpose, code),
            idempotency_key=str(row.id),
        )
    except ProviderError:
        # Kill the credential, keep the history. Committed rather than
        # flushed because the raise below reaches get_db, which rolls back.
        row.consumed_at = _now()
        db.commit()
        raise


def consume_code(
    db: Session, user: AppUser, purpose: AuthCodePurpose, code: str
) -> None:
    """Verify and burn a code. Raises CodeInvalid for every failure mode."""
    row = _live_code(db, user.id, purpose)
    if row is None:
        raise CodeInvalid()

    now = _now()
    if _aware(row.expires_at) <= now:
        row.consumed_at = now
        db.commit()
        raise CodeInvalid()

    if hmac.compare_digest(row.code_hash, _hash_code(code)):
        row.consumed_at = now
        db.flush()
        return

    row.attempts += 1
    if row.attempts >= MAX_ATTEMPTS:
        row.consumed_at = now
    # THE critical commit in this module. get_db rolls the request back when
    # CodeInvalid becomes a 400, so without this the counter resets on every
    # wrong guess and the five-attempt limit does not exist at all.
    db.commit()
    raise CodeInvalid()


def mark_email_verified(db: Session, user: AppUser) -> None:
    """Records that the address is proven reachable.

    Set from a code confirmation, and also from a Google sign-in or a
    completed password reset — anything that establishes the same fact
    should record it the same way rather than each caller inventing its own
    timestamp handling.
    """
    if user.email_verified_at is None:
        user.email_verified_at = _now()
        db.flush()
