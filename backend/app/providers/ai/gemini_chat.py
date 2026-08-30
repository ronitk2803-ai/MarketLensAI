"""Tool-calling Gemini client for the NL research assistant
(Build_plan.md §N/§S step 25, Screener.md §18) — a different shape from
gemini_summary.py's single-shot text generation, so it's a separate module
rather than a second mode bolted onto that one (product_principles.md:
"a new feature = new module + existing interfaces, not a rewrite").

Reuses gemini_summary.py's MODEL_FALLBACK_CHAIN — same models, same
reasoning (see that module's docstring for the two-bug saga that produced
it) — but not its request loop: a single-shot text generation and a
one-turn step in a multi-turn tool-calling conversation send and parse
different request/response shapes, and forcing them through one shared
loop would have made both harder to read for the sake of avoiding this
one duplicated (model, key) iteration. If a third caller needs the same
fallback shape, that's the point to extract it — not before.

**Native function calling, not a prompted "emit JSON" convention.**
Verified live 2026-08-30 (the same night MODEL_FALLBACK_CHAIN was
chosen): `gemini-flash-lite-latest` handles a real `tools` +
`functionCall` / `functionResponse` round trip correctly and quickly, on
both configured keys. The `?key=` query-param bug and the
`gemini-flash-latest` overload bug that motivated all that live testing
both looked, from the outside, like "tool calling doesn't work on this
key" — it never was that; every failure was traceable to auth placement
or a specific overloaded model, not to the tools feature itself.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.ai.gemini_summary import MODEL_FALLBACK_CHAIN
from app.providers.errors import ProviderError

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Looser than gemini_summary.py's single-call budget: one user question can
# take several tool-calling turns (each its own (model, key) fallback
# sweep), not one call. Bounds the *whole* conversation, not one turn —
# app/services/research_assistant.py's turn cap (MAX_TOOL_CALLS) is what
# actually stops a runaway loop; this is the backstop under it.
_TOTAL_DEADLINE_SECONDS = 55.0
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class FunctionCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StepResult:
    """Exactly one of `function_call`/`text` is set — a call the caller
    must dispatch, or the model's final answer. Never both: a functionCall
    part means the model chose not to answer yet, so there is no text to
    also return.

    `raw_part` is the *exact* part Gemini returned, kept verbatim rather
    than reconstructed from `function_call`. Verified live 2026-08-30:
    Gemini's newer models attach a `thoughtSignature` to a functionCall
    part and reject the next turn with a 400 ("missing thought_signature")
    if the caller reconstructs the model's own turn from scratch instead
    of echoing that field back unchanged — so the caller
    (app/services/research_assistant.py) must append `raw_part` itself
    into the next turn's `contents`, not a hand-built
    `{"functionCall": {...}}` dict."""

    function_call: FunctionCall | None
    text: str | None
    raw_part: dict[str, Any]


def _post_with_fallback(
    client: httpx.Client, body: dict, api_keys: list[str], models: list[str]
) -> dict:
    """One (model, key) fallback sweep for one turn — see the module
    docstring on why this doesn't share gemini_summary.py's version of
    the same loop. Returns the parsed JSON body of the first 200; raises
    the last error once every combination is exhausted."""
    deadline = time.monotonic() + _TOTAL_DEADLINE_SECONDS
    combinations = [(model, key) for model in models for key in api_keys]
    last_error: ProviderError | None = None
    for index, (model, api_key) in enumerate(combinations):
        remaining = deadline - time.monotonic()
        # Guaranteed at least one attempt regardless of the clock — see
        # gemini_summary.py's identical guard and the regression test
        # that exists because omitting this once already shipped a bug.
        if index > 0 and remaining <= 0:
            break
        try:
            response = client.post(
                API_URL.format(model=model),
                headers={"x-goog-api-key": api_key},
                json=body,
                timeout=httpx.Timeout(
                    connect=_CONNECT_TIMEOUT,
                    read=min(_READ_TIMEOUT, max(remaining, 1.0)),
                    write=5.0,
                    pool=5.0,
                ),
            )
        except httpx.HTTPError as error:
            last_error = ProviderError("gemini_chat", f"request failed: {error}", retryable=True)
            continue

        if response.status_code == 429:
            last_error = ProviderError("gemini_chat", "rate limited", retryable=True)
            continue
        if response.status_code != 200:
            text = response.text[:500]
            last_error = ProviderError(
                "gemini_chat",
                f"request failed: {response.status_code}: {text}",
                retryable=response.status_code >= 500,
            )
            continue
        return response.json()  # type: ignore[no-any-return]

    assert last_error is not None
    raise last_error


class GeminiChatProvider:
    """One turn of a tool-calling conversation. The caller
    (app/services/research_assistant.py) owns the conversation history
    and the loop across turns — this class is deliberately stateless
    between calls, the same reason GeminiSummaryProvider takes the whole
    prompt each time rather than accumulating state itself."""

    name = "gemini_chat"

    def __init__(
        self,
        api_keys: list[str],
        *,
        models: list[str] = MODEL_FALLBACK_CHAIN,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_keys:
            raise ValueError("GeminiChatProvider needs at least one API key")
        self._api_keys = api_keys
        self._models = models
        self._client = client

    def step(
        self,
        *,
        system_instruction: str,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> StepResult:
        """One request/response turn. `contents` is the full conversation
        so far (the caller's responsibility to accumulate — see
        research_assistant.py's ask()); this never mutates it."""
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0
            )
        )
        try:
            body = {
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": contents,
                "tools": [{"functionDeclarations": tools}] if tools else [],
            }
            payload = _post_with_fallback(client, body, self._api_keys, self._models)
            try:
                candidate = payload["candidates"][0]
                part = candidate["content"]["parts"][0]
            except (KeyError, IndexError) as error:
                # Same "safety filter blocked it" outcome
                # gemini_summary.py documents — a real, if rare, 200 with
                # no usable content, not a parsing bug.
                raise ProviderError("gemini_chat", "empty response — no candidates") from error

            if "functionCall" in part:
                call = part["functionCall"]
                return StepResult(
                    function_call=FunctionCall(name=call["name"], args=call.get("args", {})),
                    text=None,
                    raw_part=part,
                )
            if "text" in part:
                return StepResult(function_call=None, text=part["text"].strip(), raw_part=part)
            raise ProviderError("gemini_chat", f"unrecognized response part: {list(part)}")
        finally:
            if owns_client:
                client.close()
