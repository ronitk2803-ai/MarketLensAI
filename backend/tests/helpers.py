"""Shared test helpers.

`auth_headers` was copy-pasted into seven API suites before it lived here.
Two things forced the consolidation: the verified-email gate means every
suite that saves something now needs its user marked verified, and the
throttles on the verification/reset codes `db.commit()` deliberately (see
app/services/company_summary.py's note on get_db rolling a flush-only row
back), which the rollback-scoped `db` fixture cannot undo. Fixed addresses
like "addlist@example.com" would therefore carry state between local runs
and fail on the second one, so addresses are unique per call.
"""

import datetime as dt
from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.db.session import get_db
from app.main import app

client = TestClient(app)

TEST_PASSWORD = "password123"


def _test_session() -> Session:
    """The session the app is currently overridden to use.

    Every API suite has an autouse `_use_test_session` fixture that points
    `get_db` at the test's rollback-scoped session. Reaching for it through
    the override — rather than taking `db` as a parameter — keeps
    `auth_headers` a drop-in for the per-file helpers it replaces, so no
    test signature had to change. A separate SessionLocal would not work:
    the user this helper registers is only flushed, never committed, so
    nothing outside that session can see it.
    """
    override = app.dependency_overrides.get(get_db)
    if override is None:
        raise RuntimeError(
            "auth_headers needs the autouse _use_test_session fixture to be active"
        )
    sessions: Iterator[Session] = override()
    return next(sessions)


def register_user(prefix: str, *, verified: bool = True) -> tuple[str, dict[str, str]]:
    """Registers a fresh account; returns its (email, Authorization header).

    Registration goes through the real endpoint rather than the service
    layer, so these tests exercise the actual token a browser would present.

    `verified=True` by default because most suites are testing something
    other than the verification gate and would otherwise all 403. Pass
    `verified=False` to test the gate itself. Verification is set directly
    on the row rather than through the API: the send path would try to
    reach Resend.

    Use this over `auth_headers` when the test also has to seed rows for
    the user it just made — the address is generated here, so the caller
    cannot know it otherwise.
    """
    db = _test_session()
    email = f"{prefix}-{uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    response.raise_for_status()

    if verified:
        user = db.query(AppUser).filter_by(email=email).one()
        user.email_verified_at = dt.datetime.now(dt.UTC)
        db.flush()

    return email, {"Authorization": f"Bearer {response.json()['access_token']}"}


def auth_headers(prefix: str, *, verified: bool = True) -> dict[str, str]:
    """`register_user` for the common case where only the header is needed."""
    return register_user(prefix, verified=verified)[1]
