"""Unit tests for GeminiSummaryProvider's retry behavior.

The retry loop has two failure shapes: an HTTP error status (5xx) and a
network-level exception (timeout, connection reset) raised by httpx itself
before any response exists. Both are marked `retryable=True`, so both need
to actually retry rather than one of them silently bypassing the loop.
"""

import httpx
import pytest

from app.providers.ai import gemini_summary
from app.providers.ai.gemini_summary import GeminiSummaryProvider
from app.providers.errors import ProviderError


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": "  a summary  "}]}}]}
    )


def test_generate_returns_stripped_text_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response()

    provider = GeminiSummaryProvider("key", client=_client(handler))
    assert provider.generate("prompt") == "a summary"


def test_generate_retries_after_a_network_level_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: a read timeout (or any httpx.HTTPError raised before
    a response exists) used to `raise` straight out of the retry loop on
    the very first attempt, even though it's marked retryable=True — so it
    never got the same second chance a 503 does. Verified live 2026-08-25:
    a single slow/overloaded-model request hung past the client's 30s
    timeout and failed the whole summary with no retry."""
    monkeypatch.setattr("app.providers.ai.gemini_summary.time.sleep", lambda _seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return _ok_response()

    provider = GeminiSummaryProvider("key", client=_client(handler))
    assert provider.generate("prompt") == "a summary"
    assert calls["n"] == 2


def test_generate_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.ai.gemini_summary.time.sleep", lambda _seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="overloaded")
        return _ok_response()

    provider = GeminiSummaryProvider("key", client=_client(handler))
    assert provider.generate("prompt") == "a summary"
    assert calls["n"] == 2


def test_generate_raises_after_exhausting_retries_on_repeated_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.providers.ai.gemini_summary.time.sleep", lambda _seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("still timing out", request=request)

    provider = GeminiSummaryProvider("key", client=_client(handler))
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate("prompt")
    assert calls["n"] == 3  # _MAX_ATTEMPTS, not 1


def test_generate_raises_when_response_has_no_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    provider = GeminiSummaryProvider("key", client=_client(handler))
    with pytest.raises(ProviderError, match="no summary in response"):
        provider.generate("prompt")


def test_generate_stops_retrying_once_the_total_deadline_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt count alone bounds nothing: 3 attempts at a 30s timeout
    plus two 2s sleeps is ~94s of a threadpool worker per click, which is
    exactly what a dead provider cost before. Retries now have to fit a
    total budget."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    # A clock that jumps past the whole budget the moment the first attempt
    # fails, so the second attempt is never made.
    ticks = iter([0.0, gemini_summary._TOTAL_DEADLINE_SECONDS + 1])
    monkeypatch.setattr(
        gemini_summary.time, "monotonic", lambda: next(ticks, 10_000.0)
    )
    monkeypatch.setattr(gemini_summary.time, "sleep", lambda _seconds: None)

    provider = GeminiSummaryProvider("key", client=_client(handler))
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate("prompt")

    assert calls["n"] == 1  # budget spent, so no second attempt


def test_an_empty_bodied_4xx_is_reported_as_a_key_authorization_problem() -> None:
    """The live symptom of a restricted key: Google answers generateContent
    with a 4xx and no body at all, on a model its own models.list says
    supports generateContent. A bare status code gives nobody anything to
    act on."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"")

    provider = GeminiSummaryProvider("key", client=_client(handler))
    with pytest.raises(ProviderError, match="not authorized to generate"):
        provider.generate("prompt")
