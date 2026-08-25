from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
