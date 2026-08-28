"""Company narrative summaries via Gemini's free tier
(generativelanguage.googleapis.com) — chosen specifically because it has a
standing no-cost tier; Anthropic's API does not (2026-08-24 design chat).

Rate-limited, not unlimited: this is only ever called from
app/services/company_summary.py's click-triggered, cache-aware path, never
on a schedule or a page load, which is what keeps usage inside the free
tier regardless of how much traffic the page gets.

--- Diagnosing a dead provider ---

**Auth must be the `x-goog-api-key` header, not a `?key=` query
parameter — this was the actual root cause of a multi-day outage, not a
console restriction.** A newer Google Cloud key type ("account-bound,"
tied to a service account rather than a bare project-level key — visible
in the console as "Only Agent Platform (Vertex) API and Gemini API are
supported by account bound keys") answers `GET /v1beta/models?key=...`
(a 200) but **hangs indefinitely on `POST .../generateContent?key=...`**
with zero bytes returned, even with every console restriction correctly
set to "None" / "Gemini API". The identical request with the key moved
from the query string to an `x-goog-api-key` header returns 200 in
~10s, verified live 2026-08-28 against a freshly-created account-bound
key — same key, same model, same body, only the auth placement changed.
Two days of investigation (2026-08-26) blamed an API-key restriction in
the Google Cloud console because the *symptom* (GET works, POST hangs,
`server: scaffolding on HTTPServer2` proving Google itself was
answering) is identical to a genuinely referrer-restricted key — but the
actual fix for an account-bound key is the header, not the console.
`generate()` below uses the header now; this docstring's diagnostic
still checks both so a real console restriction on an *older*-style key
is still distinguishable from this.

    KEY=$(grep '^GEMINI_API_KEY=' backend/.env | cut -d= -f2-)
    # Header auth — what the app actually does. If this 200s, the key works.
    curl -s -o /dev/null -w '%{http_code} %{time_total}s\\n' \\
      -H "x-goog-api-key: $KEY" -H 'Content-Type: application/json' \\
      -d '{"contents":[{"parts":[{"text":"ok"}]}]}' \\
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    # Query-param auth — kept only to distinguish "this key needs the
    # header" (query hangs, header above 200s) from "this key is
    # genuinely dead" (both fail identically).
    curl -s -o /dev/null -w '%{http_code} %{time_total}s\\n' \\
      -H 'Content-Type: application/json' \\
      -d '{"contents":[{"parts":[{"text":"ok"}]}]}' \\
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=$KEY"

If the header form also hangs or 404s empty-bodied, *then* it's a real
console restriction (Application restrictions / API restrictions) or a
dead key — check those next. If the GET to `/v1beta/models` fails too,
it's the key or the network; if a POST 404s *with* a JSON body naming
the model, the model was retired.
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

# Total wall-clock budget across every attempt. The attempt count alone
# doesn't bound anything: 3 attempts at a flat 30s plus two 2s sleeps is
# ~94 seconds, and because the endpoint is a sync `def` that is 94 seconds
# of a threadpool worker held open per click. Retries still exist (a read
# timeout genuinely deserves a second chance — see the handler below), but
# they now have to fit inside this budget.
_TOTAL_DEADLINE_SECONDS = 45.0

# Split rather than one flat value: a connect stall means the host is
# unreachable and should be given up on quickly, whereas a slow generation
# is the normal case and needs real room.
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 25.0
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
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0
            )
        )
        deadline = time.monotonic() + _TOTAL_DEADLINE_SECONDS
        try:
            last_error: ProviderError | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                remaining = deadline - time.monotonic()
                if attempt > 1 and remaining <= 0:
                    # Budget spent. Whatever the last failure was is the
                    # honest thing to report — inventing a "timed out
                    # overall" message would hide which call actually broke.
                    break
                try:
                    response = client.post(
                        API_URL.format(model=self._model),
                        # Header, not `params={"key": ...}` — see the
                        # module docstring. A `?key=` query param hangs
                        # indefinitely for an account-bound key even with
                        # every console restriction set correctly; the
                        # header works identically for both key types, so
                        # it's the right default regardless of which kind
                        # of key is configured.
                        headers={"x-goog-api-key": self._api_key},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        # Clamped so a final attempt can't run past the
                        # budget. Only narrows the read leg; connect stays
                        # short regardless.
                        timeout=httpx.Timeout(
                            connect=_CONNECT_TIMEOUT,
                            read=min(_READ_TIMEOUT, max(remaining, 1.0)),
                            write=5.0,
                            pool=5.0,
                        ),
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
                    body = response.text[:500]
                    # Google returns a JSON error body for genuine problems
                    # (bad model, malformed request). A 4xx with an *empty*
                    # body, on a model that models.list says supports
                    # generateContent, is the signature of a key that can
                    # read but not generate — say so rather than reporting a
                    # bare status nobody can act on. See the module
                    # docstring for the one-command confirmation.
                    if not body.strip() and 400 <= response.status_code < 500:
                        body = (
                            "empty response body — the API key is likely valid but not "
                            "authorized to generate (check API-key restrictions in the "
                            "Google Cloud console); see this module's docstring to confirm"
                        )
                    last_error = ProviderError(
                        "gemini_summary",
                        f"generate failed: {response.status_code}: {body}",
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
