import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.providers.auth import upstox_token_manager

client = TestClient(app)


@pytest.fixture
def admin_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-secret")
    get_settings.cache_clear()
    yield "test-admin-secret"
    get_settings.cache_clear()


def test_admin_endpoint_rejects_missing_token(admin_token: str) -> None:
    response = client.post("/api/v1/admin/upstox/token", json={"code": "abc"})
    assert response.status_code == 401


def test_admin_endpoint_rejects_wrong_token(admin_token: str) -> None:
    response = client.post(
        "/api/v1/admin/upstox/token",
        json={"code": "abc"},
        headers={"X-Admin-Token": "wrong"},
    )
    assert response.status_code == 401


def test_admin_endpoint_disabled_when_no_admin_token_configured() -> None:
    get_settings.cache_clear()
    response = client.post(
        "/api/v1/admin/upstox/token",
        json={"code": "abc"},
        headers={"X-Admin-Token": "anything"},
    )
    assert response.status_code == 401


def test_admin_endpoint_exchanges_code_with_correct_token(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.v1.admin.exchange_code_for_token", lambda code: "fresh-token"
    )
    upstox_token_manager.token_manager = upstox_token_manager.UpstoxTokenManager()
    monkeypatch.setattr("app.api.v1.admin.token_manager", upstox_token_manager.token_manager)

    response = client.post(
        "/api/v1/admin/upstox/token",
        json={"code": "abc"},
        headers={"X-Admin-Token": admin_token},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert upstox_token_manager.token_manager.get_token() == "fresh-token"
