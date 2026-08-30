"""Unit tests for GeminiSummaryProvider's (model, key) fallback loop.

Two independent axes of fallback, verified separately: a different model
clears a model-overload failure (503/network error), and a different key
clears a key-specific failure (429). Models are the outer loop and keys
the inner one — see the module docstring on gemini_summary.py for why.
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

    provider = GeminiSummaryProvider(["key"], client=_client(handler))
    assert provider.generate("prompt") == "a summary"


def test_constructor_rejects_an_empty_key_list() -> None:
    with pytest.raises(ValueError):
        GeminiSummaryProvider([])


def test_generate_falls_back_to_the_next_model_on_a_network_error() -> None:
    """A network-level failure (timeout, connection reset) on the first
    model in the chain moves to the second rather than retrying the same
    (model, key) combination — verified live 2026-08-30: a genuinely
    overloaded model fails identically on a second identical request."""
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = str(request.url).split("/models/")[1].split(":")[0]
        seen_models.append(model)
        if len(seen_models) == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return _ok_response()

    provider = GeminiSummaryProvider(
        ["key"], models=["model-a", "model-b"], client=_client(handler)
    )
    assert provider.generate("prompt") == "a summary"
    assert seen_models == ["model-a", "model-b"]


def test_generate_falls_back_to_the_next_model_on_5xx() -> None:
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = str(request.url).split("/models/")[1].split(":")[0]
        seen_models.append(model)
        if len(seen_models) == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _ok_response()

    provider = GeminiSummaryProvider(
        ["key"], models=["model-a", "model-b"], client=_client(handler)
    )
    assert provider.generate("prompt") == "a summary"
    assert seen_models == ["model-a", "model-b"]


def test_generate_falls_back_to_a_different_key_on_429() -> None:
    """A 429 no longer raises immediately (the old single-key behavior) —
    it's exactly the case a second key in the pool exists for."""
    seen_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers["x-goog-api-key"])
        if len(seen_keys) == 1:
            return httpx.Response(429, text="rate limited")
        return _ok_response()

    provider = GeminiSummaryProvider(["key-1", "key-2"], client=_client(handler))
    assert provider.generate("prompt") == "a summary"
    assert seen_keys == ["key-1", "key-2"]


def test_generate_tries_models_outer_keys_inner() -> None:
    """Exhausts every key on the first model before moving to the second
    model — a model-overload failure is more likely to repeat across keys
    (same overloaded backend) than a key failure is to repeat across
    models, so this order wastes fewer combinations on average."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = str(request.url).split("/models/")[1].split(":")[0]
        key = request.headers["x-goog-api-key"]
        seen.append((model, key))
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    provider = GeminiSummaryProvider(
        ["key-1", "key-2"], models=["model-a", "model-b"], client=_client(handler)
    )
    with pytest.raises(ProviderError):
        provider.generate("prompt")

    assert seen == [
        ("model-a", "key-1"),
        ("model-a", "key-2"),
        ("model-b", "key-1"),
        ("model-b", "key-2"),
    ]


def test_generate_raises_after_exhausting_every_combination() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("still timing out", request=request)

    provider = GeminiSummaryProvider(
        ["key-1", "key-2"], models=["model-a", "model-b"], client=_client(handler)
    )
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate("prompt")
    assert calls["n"] == 4  # 2 models x 2 keys, none skipped


def test_generate_raises_when_response_has_no_candidates() -> None:
    """A safety-filtered empty response isn't something any other (model,
    key) combination would answer differently, so this raises immediately
    rather than burning through the rest of the chain."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"candidates": []})

    provider = GeminiSummaryProvider(["key-1", "key-2"], client=_client(handler))
    with pytest.raises(ProviderError, match="no summary in response"):
        provider.generate("prompt")
    assert calls["n"] == 1


def test_generate_always_makes_at_least_one_attempt_even_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the deadline check must never suppress the very
    first attempt, or last_error stays None and the internal `assert`
    raises a bare AssertionError instead of a real ProviderError."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    # Clock already past the deadline before the very first attempt.
    ticks = iter([0.0, gemini_summary._TOTAL_DEADLINE_SECONDS + 1])
    monkeypatch.setattr(gemini_summary.time, "monotonic", lambda: next(ticks, 10_000.0))

    provider = GeminiSummaryProvider(["key-1", "key-2"], client=_client(handler))
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate("prompt")
    assert calls["n"] == 1  # the guaranteed first attempt, then budget stops the rest


def test_generate_stops_once_the_total_deadline_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    # First monotonic() call sets the deadline; the second (checked before
    # combination 2) has already jumped past it.
    ticks = iter([0.0, 0.0, gemini_summary._TOTAL_DEADLINE_SECONDS + 1])
    monkeypatch.setattr(gemini_summary.time, "monotonic", lambda: next(ticks, 10_000.0))

    provider = GeminiSummaryProvider(
        ["key-1", "key-2"], models=["model-a"], client=_client(handler)
    )
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate("prompt")
    assert calls["n"] == 1  # budget spent before combination 2


def test_an_empty_bodied_4xx_names_the_header_auth_fix() -> None:
    """The live signature of Bug 1 (see module docstring): Google answers
    generateContent with a 4xx and no body at all, on a model its own
    models.list says supports generateContent. A bare status code gives
    nobody anything to act on."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"")

    provider = GeminiSummaryProvider(["key"], client=_client(handler))
    with pytest.raises(ProviderError, match="header auth"):
        provider.generate("prompt")
