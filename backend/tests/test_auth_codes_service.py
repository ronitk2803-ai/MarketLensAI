import datetime as dt
import re

import pytest
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthCode
from app.db.session import SessionLocal
from app.providers.errors import ProviderError
from app.services import auth_codes as ac
from app.services.auth_codes import (
    MAX_ATTEMPTS,
    MAX_SENDS_PER_HOUR,
    CodeInvalid,
    CodeThrottled,
    consume_code,
    send_code,
)


@pytest.fixture
def user(db: Session) -> AppUser:
    row = AppUser(email="codes@example.com", hashed_password="not-a-real-hash")
    db.add(row)
    db.flush()
    return row


@pytest.fixture(autouse=True)
def _cleanup(db: Session):
    """send_code and consume_code commit deliberately (see the module
    docstring), so the rollback-scoped `db` fixture cannot undo their rows.
    Sweep them by hand, mirroring test_company_summary.py's approach."""
    yield
    db.rollback()
    ids = [r[0] for r in db.query(AppUser.id).filter(AppUser.email.like("codes%@example.com"))]
    if ids:
        db.query(AuthCode).filter(AuthCode.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(AppUser).filter(AppUser.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def _capture_sends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Intercepts the provider and returns the codes it was asked to email —
    the only place a test can see a code, since nothing else ever exposes
    one."""
    sent: list[str] = []

    class _Stub:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        def send(self, *, to: str, subject: str, text: str, **kwargs: object) -> str:
            # The code sits alone on its own indented line; a naive
            # digits-only scan would also swallow the "10" from "expires in
            # 10 minutes" and silently produce a wrong code.
            match = re.search(r"^\s+(\d{6})\s*$", text, re.M)
            assert match is not None, text
            sent.append(match.group(1))
            return "msg-1"

    monkeypatch.setattr(ac, "ResendEmailProvider", _Stub)

    class _Settings:
        resend_api_key = "re_test"
        resend_from_email = "test@example.com"
        jwt_secret = "test-secret"

    monkeypatch.setattr(ac, "get_settings", lambda: _Settings())
    return sent


def test_a_correct_code_verifies_and_is_then_spent(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")

    consume_code(db, user, "verify_email", sent[0])

    # Single-use: replaying the same code must not work.
    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", sent[0])


def test_a_wrong_code_is_rejected(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")
    wrong = "000000" if sent[0] != "000000" else "111111"

    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", wrong)


def test_a_wrong_attempt_survives_the_rollback_that_follows_it(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE regression test for this module. CodeInvalid becomes a 400, and
    get_db rolls the request back on any exception — so a flush-only
    increment would vanish with it and the attempt limit would not exist,
    leaving a 6-digit code guessable in 10^6 requests.

    Asserted through a SEPARATE session, because the test's own session
    would show the in-memory value whether or not it was ever committed."""
    _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")
    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", "000000")

    observer = SessionLocal()
    try:
        row = observer.query(AuthCode).filter_by(user_id=user.id).one()
        assert row.attempts == 1
    finally:
        observer.close()


def test_the_code_dies_after_too_many_wrong_attempts(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")
    wrong = "000000" if sent[0] != "000000" else "111111"

    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(CodeInvalid):
            consume_code(db, user, "verify_email", wrong)

    # Even the RIGHT code is now dead — the budget guards the code, not the
    # guess.
    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", sent[0])


def test_an_expired_code_is_rejected(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")

    # Back-date the row, the same technique the refresh-token TTL tests use.
    row = db.query(AuthCode).filter_by(user_id=user.id, consumed_at=None).one()
    row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db.commit()

    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", sent[0])


def test_resending_supersedes_the_previous_code(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Several live codes would multiply the guess surface while sharing one
    attempt budget, so the old one is retired. Also exercises the flush
    ordering the partial unique index demands."""
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")
    _advance_past_cooldown(db, user)
    send_code(db, user, "verify_email")

    assert len(sent) == 2
    with pytest.raises(CodeInvalid):
        consume_code(db, user, "verify_email", sent[0])
    consume_code(db, user, "verify_email", sent[1])


def _advance_past_cooldown(db: Session, user: AppUser) -> None:
    """Back-dates every code so the 60s spacing rule no longer applies."""
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
    for row in db.query(AuthCode).filter_by(user_id=user.id):
        row.created_at = past
    db.commit()


def test_a_second_send_inside_the_cooldown_is_throttled(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")

    with pytest.raises(CodeThrottled):
        send_code(db, user, "verify_email")


def test_the_hourly_ceiling_stops_further_sends(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_sends(monkeypatch)
    for _ in range(MAX_SENDS_PER_HOUR):
        send_code(db, user, "verify_email")
        _advance_past_cooldown(db, user)

    with pytest.raises(CodeThrottled):
        send_code(db, user, "verify_email")


def test_a_failed_send_kills_the_code_but_keeps_the_throttle(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is both the credential and the throttle record. Rolling it
    back to avoid an unusable code would also erase the evidence a send was
    attempted, letting a caller hammer a broken provider."""
    _capture_sends(monkeypatch)

    class _Broken:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        def send(self, **kwargs: object) -> str:
            raise ProviderError("resend", "boom")

    monkeypatch.setattr(ac, "ResendEmailProvider", _Broken)

    with pytest.raises(ProviderError):
        send_code(db, user, "verify_email")

    observer = SessionLocal()
    try:
        rows = observer.query(AuthCode).filter_by(user_id=user.id).all()
        assert len(rows) == 1  # the throttle record survived the rollback
        assert rows[0].consumed_at is not None  # ...but the code is dead
    finally:
        observer.close()

    # And the throttle it left behind is enforced.
    monkeypatch.setattr(ac, "ResendEmailProvider", _Broken)
    with pytest.raises(CodeThrottled):
        send_code(db, user, "verify_email")


def test_purposes_do_not_share_a_code_or_a_throttle(
    db: Session, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_sends(monkeypatch)
    send_code(db, user, "verify_email")
    # Not throttled: the cooldown is per purpose.
    send_code(db, user, "password_reset")

    with pytest.raises(CodeInvalid):
        consume_code(db, user, "password_reset", sent[0])
    consume_code(db, user, "password_reset", sent[1])
