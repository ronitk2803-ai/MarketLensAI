"""Company narrative summaries via Gemini's free tier
(generativelanguage.googleapis.com) — chosen specifically because it has a
standing no-cost tier; Anthropic's API does not (2026-08-24 design chat).

Rate-limited, not unlimited: this is only ever called from
app/services/company_summary.py's click-triggered, cache-aware path, never
on a schedule or a page load, which is what keeps usage inside the free
tier regardless of how much traffic the page gets.
"""

import time

import httpx

from app.providers.errors import ProviderError

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Google's flash-latest alias is popular enough that "model overloaded" 503s
# are common in practice, not exceptional (verified live 2026-08-24) — a
# couple of short retries clears most of them without the user ever seeing
# an error for what is, from their side, one button click.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0
# An alias Google keeps pointed at their current recommended flash model,
# rather than a pinned version — pinned versions get retired periodically
# (this is exactly what broke "gemini-2.0-flash" here, verified live
# 2026-08-24) and a retired model 404s instead of degrading gracefully.
DEFAULT_MODEL = "gemini-flash-latest"


class GeminiSummaryProvider:
    """Thin wrapper over the REST API (no SDK dependency, same style as
    app/providers/india/google_news.py's direct httpx use)."""

    name = "gemini_summary"

    def __init__(
        self, api_key: str, *, model: str = DEFAULT_MODEL, client: httpx.Client | None = None
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    def generate(self, prompt: str) -> str:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            last_error: ProviderError | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = client.post(
                        API_URL.format(model=self._model),
                        params={"key": self._api_key},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                    )
                except httpx.HTTPError as error:
                    # Network-level failure (timeout, connection reset) —
                    # marked retryable, so it needs to actually go through
                    # the same retry-with-backoff path as a 5xx below rather
                    # than raising straight out of the loop on the very
                    # first attempt. A slow/overloaded model read-timing-out
                    # is at least as common as it returning a 503 outright
                    # (verified live 2026-08-25: a single request to Gemini
                    # hung past the 30s client timeout), so this needs the
                    # same tolerance.
                    last_error = ProviderError(
                        "gemini_summary", f"request failed: {error}", retryable=True
                    )
                    if attempt < _MAX_ATTEMPTS:
                        time.sleep(_RETRY_DELAY_SECONDS)
                        continue
                    raise last_error from error

                if response.status_code == 429:
                    raise ProviderError("gemini_summary", "rate limited", retryable=True)
                if response.status_code != 200:
                    last_error = ProviderError(
                        "gemini_summary",
                        f"generate failed: {response.status_code}: {response.text[:500]}",
                        retryable=response.status_code >= 500,
                    )
                    if last_error.retryable and attempt < _MAX_ATTEMPTS:
                        time.sleep(_RETRY_DELAY_SECONDS)
                        continue
                    raise last_error

                payload = response.json()
                try:
                    candidate = payload["candidates"][0]
                    return "".join(
                        part["text"] for part in candidate["content"]["parts"]
                    ).strip()
                except (KeyError, IndexError) as error:
                    # Gemini returns 200 with no candidates when its own
                    # safety filter blocks the output — a real, if rare,
                    # outcome, not a parsing bug, so it shouldn't look like
                    # a crash upstream, and retrying won't fix it.
                    raise ProviderError("gemini_summary", "no summary in response") from error
            # Reachable only by exhausting every attempt, and each iteration
            # that doesn't return or raise directly sets last_error first —
            # so it's genuinely always set here, mypy just can't see that
            # across the loop.
            assert last_error is not None
            raise last_error
        finally:
            if owns_client:
                client.close()
