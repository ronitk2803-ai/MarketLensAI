from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.providers.ai.gemini_chat import FunctionCall, GeminiChatProvider, StepResult
from tests.helpers import auth_headers

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _stub_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file must be network-free — GeminiChatProvider
    itself is monkeypatched per-test where a call actually needs to
    happen; this just ensures the "not configured" 502 branch never
    fires because the test environment happens to have no key."""
    settings = get_settings()
    monkeypatch.setattr(type(settings), "gemini_api_keys", property(lambda self: ["test-key"]))


def test_ask_requires_authentication() -> None:
    response = client.post("/api/v1/assistant/ask", json={"question": "hello?"})
    assert response.status_code == 401


def test_ask_requires_a_non_empty_question() -> None:
    headers = auth_headers("assistant-empty")
    response = client.post("/api/v1/assistant/ask", json={"question": ""}, headers=headers)
    assert response.status_code == 422


def test_ask_returns_the_answer_and_tools_used(monkeypatch: pytest.MonkeyPatch) -> None:
    steps = iter(
        [
            StepResult(
                function_call=FunctionCall(name="get_my_watchlist", args={}),
                text=None,
                raw_part={"functionCall": {"name": "get_my_watchlist", "args": {}}},
            ),
            StepResult(function_call=None, text="Your watchlist is empty.", raw_part={}),
        ]
    )
    monkeypatch.setattr(GeminiChatProvider, "step", lambda self, **kwargs: next(steps))

    headers = auth_headers("assistant-happy")
    response = client.post(
        "/api/v1/assistant/ask", json={"question": "what's on my watchlist?"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Your watchlist is empty."
    assert body["tools_used"] == ["get_my_watchlist"]


def test_ask_maps_a_provider_error_to_a_502(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.errors import ProviderError

    def boom(self: GeminiChatProvider, **kwargs: object) -> StepResult:
        raise ProviderError("gemini_chat", "simulated outage")

    monkeypatch.setattr(GeminiChatProvider, "step", boom)

    headers = auth_headers("assistant-error")
    response = client.post(
        "/api/v1/assistant/ask", json={"question": "anything"}, headers=headers
    )
    assert response.status_code == 502


def test_ask_502s_with_a_clear_message_when_no_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(type(settings), "gemini_api_keys", property(lambda self: []))

    headers = auth_headers("assistant-nokey")
    response = client.post("/api/v1/assistant/ask", json={"question": "anything"}, headers=headers)

    assert response.status_code == 502
    assert "GEMINI_API_KEY_1" in response.json()["detail"]


def test_ask_requires_email_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = auth_headers("assistant-unverified", verified=False)
    response = client.post("/api/v1/assistant/ask", json={"question": "anything"}, headers=headers)
    assert response.status_code == 403
