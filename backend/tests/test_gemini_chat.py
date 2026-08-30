import httpx
import pytest

from app.providers.ai import gemini_chat
from app.providers.ai.gemini_chat import GeminiChatProvider
from app.providers.errors import ProviderError


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _function_call_response(name: str = "get_thing", args: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {"name": name, "args": args or {"symbol": "X"}},
                                "thoughtSignature": "opaque-signature-123",
                            }
                        ],
                        "role": "model",
                    }
                }
            ]
        },
    )


def _text_response(text: str = "final answer") -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}
    )


def test_step_parses_a_function_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _function_call_response("get_score", {"symbol": "RELIANCE"})

    provider = GeminiChatProvider(["key"], client=_client(handler))
    result = provider.step(system_instruction="sys", contents=[], tools=[])

    assert result.text is None
    assert result.function_call is not None
    assert result.function_call.name == "get_score"
    assert result.function_call.args == {"symbol": "RELIANCE"}


def test_step_preserves_the_raw_part_verbatim_for_round_tripping() -> None:
    """The exact bug found live 2026-08-30: Gemini rejects the next turn
    with a 400 if the caller reconstructs the model's own functionCall
    part instead of echoing back fields like thoughtSignature unchanged.
    This is why StepResult carries raw_part at all."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _function_call_response()

    provider = GeminiChatProvider(["key"], client=_client(handler))
    result = provider.step(system_instruction="sys", contents=[], tools=[])

    assert result.raw_part["thoughtSignature"] == "opaque-signature-123"
    assert result.raw_part["functionCall"]["name"] == "get_thing"


def test_step_parses_final_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("here is the answer")

    provider = GeminiChatProvider(["key"], client=_client(handler))
    result = provider.step(system_instruction="sys", contents=[], tools=[])

    assert result.function_call is None
    assert result.text == "here is the answer"


def test_step_sends_system_instruction_contents_and_tools() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return _text_response()

    provider = GeminiChatProvider(["key"], client=_client(handler))
    contents = [{"role": "user", "parts": [{"text": "hi"}]}]
    tools = [{"name": "t", "description": "d", "parameters": {"type": "OBJECT", "properties": {}}}]
    provider.step(system_instruction="be helpful", contents=contents, tools=tools)

    assert seen["systemInstruction"] == {"parts": [{"text": "be helpful"}]}
    assert seen["contents"] == contents
    assert seen["tools"] == [{"functionDeclarations": tools}]


def test_step_sends_empty_tools_list_when_none_given() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return _text_response()

    provider = GeminiChatProvider(["key"], client=_client(handler))
    provider.step(system_instruction="sys", contents=[], tools=[])
    assert seen["tools"] == []


def test_constructor_rejects_an_empty_key_list() -> None:
    with pytest.raises(ValueError):
        GeminiChatProvider([])


def test_step_falls_back_to_the_next_model_on_5xx() -> None:
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = str(request.url).split("/models/")[1].split(":")[0]
        seen_models.append(model)
        if len(seen_models) == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _text_response()

    provider = GeminiChatProvider(
        ["key"], models=["model-a", "model-b"], client=_client(handler)
    )
    result = provider.step(system_instruction="sys", contents=[], tools=[])
    assert result.text == "final answer"
    assert seen_models == ["model-a", "model-b"]


def test_step_falls_back_to_a_different_key_on_429() -> None:
    seen_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers["x-goog-api-key"])
        if len(seen_keys) == 1:
            return httpx.Response(429, text="rate limited")
        return _text_response()

    provider = GeminiChatProvider(["key-1", "key-2"], client=_client(handler))
    result = provider.step(system_instruction="sys", contents=[], tools=[])
    assert result.text == "final answer"
    assert seen_keys == ["key-1", "key-2"]


def test_step_raises_when_every_combination_is_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = GeminiChatProvider(["key-1", "key-2"], models=["model-a"], client=_client(handler))
    with pytest.raises(ProviderError, match="request failed"):
        provider.step(system_instruction="sys", contents=[], tools=[])


def test_step_always_makes_at_least_one_attempt_even_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    ticks = iter([0.0, gemini_chat._TOTAL_DEADLINE_SECONDS + 1])
    monkeypatch.setattr(gemini_chat.time, "monotonic", lambda: next(ticks, 10_000.0))

    provider = GeminiChatProvider(["key"], client=_client(handler))
    with pytest.raises(ProviderError, match="request failed"):
        provider.step(system_instruction="sys", contents=[], tools=[])
    assert calls["n"] == 1


def test_step_raises_when_response_has_no_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    provider = GeminiChatProvider(["key"], client=_client(handler))
    with pytest.raises(ProviderError, match="empty response"):
        provider.step(system_instruction="sys", contents=[], tools=[])
