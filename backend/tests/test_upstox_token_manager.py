import datetime as dt

import httpx
import pytest

from app.core.config import get_settings
from app.providers.auth.upstox_token_manager import IST, UpstoxTokenManager, exchange_code_for_token
from app.providers.errors import ProviderError


@pytest.fixture
def configured_upstox_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTOX_API_KEY", "test-key")
    monkeypatch.setenv("UPSTOX_API_SECRET", "test-secret")
    monkeypatch.setenv("UPSTOX_REDIRECT_URI", "https://example.com/callback")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_token_raises_when_never_set() -> None:
    manager = UpstoxTokenManager()
    with pytest.raises(ProviderError):
        manager.get_token()
    assert not manager.is_valid()


def test_set_token_then_get_token_returns_it() -> None:
    manager = UpstoxTokenManager()
    manager.set_token("abc123", obtained_at=dt.datetime(2026, 8, 23, 9, 0, tzinfo=IST))
    assert manager.get_token() == "abc123"
    assert manager.is_valid()


def test_token_obtained_before_expiry_hour_expires_same_day() -> None:
    manager = UpstoxTokenManager()
    manager.set_token("abc123", obtained_at=dt.datetime(2026, 8, 23, 9, 0, tzinfo=IST))
    assert manager._expires_at == dt.datetime(2026, 8, 23, 3, 30, tzinfo=IST) + dt.timedelta(days=1)


def test_token_obtained_after_expiry_hour_expires_next_day() -> None:
    manager = UpstoxTokenManager()
    manager.set_token("abc123", obtained_at=dt.datetime(2026, 8, 23, 2, 0, tzinfo=IST))
    assert manager._expires_at == dt.datetime(2026, 8, 23, 3, 30, tzinfo=IST)


def test_get_token_raises_once_expired() -> None:
    manager = UpstoxTokenManager()
    manager.set_token("abc123", obtained_at=dt.datetime(2020, 1, 1, 9, 0, tzinfo=IST))
    with pytest.raises(ProviderError):
        manager.get_token()


def test_exchange_code_for_token_success(configured_upstox_credentials: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/login/authorization/token"
        return httpx.Response(200, json={"access_token": "tok_live"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = exchange_code_for_token("one-time-code", client=client)
    assert token == "tok_live"


def test_exchange_code_for_token_upstream_error(configured_upstox_credentials: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        exchange_code_for_token("stale-code", client=client)


def test_exchange_code_for_token_not_configured() -> None:
    with pytest.raises(ProviderError):
        exchange_code_for_token("some-code")
