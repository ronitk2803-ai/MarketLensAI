import re
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthCode, RefreshToken
from app.db.session import get_db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_register_returns_tokens() -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "new@example.com", "password": "password123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_register_rejects_a_short_password() -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "short@example.com", "password": "abc"}
    )
    assert response.status_code == 400


def test_register_rejects_a_duplicate_email() -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )

    response = client.post(
        "/api/v1/auth/register", json={"email": "dup@example.com", "password": "password456"}
    )

    assert response.status_code == 409


def test_register_rejects_an_invalid_email() -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "password123"}
    )
    assert response.status_code == 422


def test_login_returns_tokens_for_correct_credentials() -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "login@example.com", "password": "password123"}
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "password123"}
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_rejects_wrong_password() -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "login2@example.com", "password": "password123"}
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "login2@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401


def test_login_rejects_unknown_email() -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "anything"}
    )
    assert response.status_code == 401


def test_me_returns_the_current_user_for_a_valid_token() -> None:
    register = client.post(
        "/api/v1/auth/register", json={"email": "me@example.com", "password": "password123"}
    )
    access_token = register.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_me_rejects_a_missing_token() -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_rejects_a_garbage_token() -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_refresh_rotates_and_returns_new_working_tokens() -> None:
    register = client.post(
        "/api/v1/auth/register", json={"email": "refresh@example.com", "password": "password123"}
    )
    refresh_token = register.json()["refresh_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    new_access_token = response.json()["access_token"]
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "refresh@example.com"


def test_refresh_rejects_a_reused_token() -> None:
    register = client.post(
        "/api/v1/auth/register", json={"email": "reuse@example.com", "password": "password123"}
    )
    refresh_token = register.json()["refresh_token"]
    client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 401


def test_logout_revokes_the_refresh_token() -> None:
    register = client.post(
        "/api/v1/auth/register", json={"email": "logout@example.com", "password": "password123"}
    )
    refresh_token = register.json()["refresh_token"]

    logout = client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 200

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


@pytest.fixture
def _stub_email(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures the code instead of sending it. Patches the module-level
    name rather than clearing get_settings' lru_cache — app/db/session.py
    binds its engine from a get_settings() call at import, so clearing the
    cache mid-run yields a Settings that no longer matches the live engine
    (the pattern test_company_summary.py established)."""
    from app.services import auth_codes as ac

    sent: list[str] = []

    class _Stub:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        def send(self, *, to: str, subject: str, text: str, **kwargs: object) -> str:
            match = re.search(r"^\s+(\d{6})\s*$", text, re.M)
            assert match is not None
            sent.append(match.group(1))
            return "msg-1"

    class _Settings:
        resend_api_key = "re_test"
        resend_from_email = "test@example.com"
        jwt_secret = "test-secret"

    monkeypatch.setattr(ac, "ResendEmailProvider", _Stub)
    monkeypatch.setattr(ac, "get_settings", lambda: _Settings())
    return sent


# The code endpoints commit deliberately (app/services/auth_codes.py explains
# why), and a commit persists the whole session — including the user the test
# just registered, which the rollback-scoped `db` fixture can then no longer
# undo. Fixed addresses would therefore survive to the next run and turn
# register into a 409. Unique per call, swept afterwards.
_CODE_TEST_DOMAIN = "@codes.example.com"


def _register(prefix: str) -> dict[str, str]:
    email = f"{prefix}-{uuid4().hex[:8]}{_CODE_TEST_DOMAIN}"
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _sweep_committed_users(db: Session) -> Iterator[None]:
    yield
    db.rollback()
    ids = [
        row[0]
        for row in db.query(AppUser.id).filter(AppUser.email.like(f"%{_CODE_TEST_DOMAIN}"))
    ]
    if ids:
        # refresh_token's FK has no ondelete cascade, and registering issues
        # one, so it has to go first.
        db.query(RefreshToken).filter(RefreshToken.user_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(AuthCode).filter(AuthCode.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(AppUser).filter(AppUser.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def test_a_new_account_starts_unverified() -> None:
    headers = _register("unverified")

    body = client.get("/api/v1/auth/me", headers=headers).json()

    assert body["email_verified"] is False
    assert body["has_password"] is True


def test_verification_round_trip(_stub_email: list[str]) -> None:
    headers = _register("verifyme")

    assert client.post("/api/v1/auth/verify-email/send", headers=headers).status_code == 200
    confirm = client.post(
        "/api/v1/auth/verify-email/confirm", json={"code": _stub_email[0]}, headers=headers
    )

    assert confirm.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).json()["email_verified"] is True


def test_a_wrong_code_is_a_400_with_a_message_that_reveals_nothing(
    _stub_email: list[str],
) -> None:
    headers = _register("wrongcode")
    client.post("/api/v1/auth/verify-email/send", headers=headers)

    response = client.post(
        "/api/v1/auth/verify-email/confirm", json={"code": "000000"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "that code is invalid or has expired"


def test_confirming_without_a_code_having_been_sent_looks_identical(
    _stub_email: list[str],
) -> None:
    """Same status and same byte-identical body as a wrong code — otherwise
    the response says whether a code was ever issued."""
    headers = _register("nocodesent")

    response = client.post(
        "/api/v1/auth/verify-email/confirm", json={"code": "123456"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "that code is invalid or has expired"


def test_resending_inside_the_cooldown_is_429(_stub_email: list[str]) -> None:
    """429 is safe here precisely because this endpoint is authenticated —
    the caller already knows the account exists, so the status leaks
    nothing. The password-reset request endpoint cannot do this."""
    headers = _register("cooldown")
    client.post("/api/v1/auth/verify-email/send", headers=headers)

    response = client.post("/api/v1/auth/verify-email/send", headers=headers)

    assert response.status_code == 429


def test_verification_endpoints_require_authentication() -> None:
    assert client.post("/api/v1/auth/verify-email/send").status_code == 401
    assert (
        client.post("/api/v1/auth/verify-email/confirm", json={"code": "123456"}).status_code
        == 401
    )


def test_sending_to_an_already_verified_account_is_a_no_op(_stub_email: list[str]) -> None:
    headers = _register("alreadyverified")
    client.post("/api/v1/auth/verify-email/send", headers=headers)
    client.post(
        "/api/v1/auth/verify-email/confirm", json={"code": _stub_email[0]}, headers=headers
    )

    response = client.post("/api/v1/auth/verify-email/send", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "already_verified"
    assert len(_stub_email) == 1  # no second email went out
