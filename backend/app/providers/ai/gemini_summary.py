"""Company narrative summaries via Gemini's free tier
(generativelanguage.googleapis.com) — chosen specifically because it has a
standing no-cost tier; Anthropic's API does not (2026-08-24 design chat).

Rate-limited, not unlimited: this is only ever called from
app/services/company_summary.py's click-triggered, cache-aware path, never
on a schedule or a page load, which is what keeps usage inside the free
tier regardless of how much traffic the page gets.

--- The two real bugs behind a multi-day "the key is broken" saga ---

**Bug 1 (fixed 2026-08-28): auth must be the `x-goog-api-key` header, not
a `?key=` query parameter.** A newer Google Cloud key type ("account-bound,"
tied to a service account rather than a bare project-level key) hung
indefinitely on `POST .../generateContent?key=...` while `GET
/v1beta/models?key=...` answered fine — a symptom that looks exactly like
a console API-key restriction (and was first, wrongly, diagnosed as one)
but isn't. Moving the key to a header fixed it for that key outright.

**Bug 2 (fixed 2026-08-30): `gemini-flash-latest` is genuinely, commonly
overloaded, independent of the key entirely.** After Bug 1 was fixed, the
exact same "hangs / fails" symptom kept recurring — but this time it
turned out to be the *model*, not the key or its auth: `gemini-flash-latest`
returned a clean, fast `503 UNAVAILABLE ("high demand")` across **two
separate Google accounts' keys**, live, repeatedly, while
`gemini-flash-lite-latest` answered instantly and correctly on both of the
same keys — including full native function-calling round trips, verified
live. A popular default alias being overloaded is exactly what this
module already warned about (see `MODEL_FALLBACK_CHAIN` below); it had
just never been distinguished from Bug 1 before because both look
identical from the outside (a 502 after a long wait, or nothing at all).

**Net effect: two independent fixes were needed, and neither one alone
would have explained everything.** `generate()` now tries every
`(model, key)` combination in order rather than retrying one combination
repeatedly — cycling to a different model is far more likely to clear a
"this specific model is overloaded right now" failure than retrying the
same overloaded model on a different key would be, which is why models
are the outer loop and keys the inner one, not the reverse.

--- Diagnosing a dead provider, if this recurs ---

    KEY=$(grep '^GEMINI_API_KEY_1=' backend/.env | cut -d= -f2-)
    # Header auth (what the app does) against each model in the fallback
    # chain — if any of these hangs/503s and another doesn't, that
    # confirms Bug 2's shape again (model-specific, not key-specific).
    for model in gemini-flash-lite-latest gemini-flash-latest; do
      curl -s -o /dev/null -w "$model: %{http_code} %{time_total}s\\n" \\
        -H "x-goog-api-key: $KEY" -H 'Content-Type: application/json' \\
        -d '{"contents":[{"parts":[{"text":"ok"}]}]}' \\
        "https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent"
    done
    # Query-param auth, for comparison — if the header form above works
    # but this hangs, that's Bug 1's shape (an account-bound key that
    # needs the header specifically).
    curl -s -o /dev/null -w '%{http_code} %{time_total}s\\n' \\
      -H 'Content-Type: application/json' \\
      -d '{"contents":[{"parts":[{"text":"ok"}]}]}' \\
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key=$KEY"

If every model hangs on every key with the header form, it's the network,
every key, or a genuine outage — not either bug above. If a POST 404s
*with* a JSON body naming the model, that model was retired (this is what
broke "gemini-2.0-flash" here on 2026-08-24, and "gemini-2.5-flash" on
2026-08-30 — pinned versions get retired periodically; `-latest` aliases
don't, which is the whole reason this module uses them despite Bug 2).
"""

import time

import httpx

from app.providers.errors import ProviderError

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Lite first, deliberately — not the "better model as primary, fall back
# to the small one" order it looks backwards from. Verified live
# 2026-08-30: gemini-flash-latest was in a sustained overloaded state
# (clean 503s, repeatedly, across two separate Google accounts) while
# gemini-flash-lite-latest answered instantly and correctly on both of
# the same accounts, including full function-calling round trips. Putting
# the reliably-overloaded model first would mean every single call pays
# for a guaranteed-fail round trip before reaching the model that
# actually works. If gemini-flash-latest is later observed healthy again,
# reordering this list is the only change needed — nothing else in this
# module encodes an assumption about which entry is "the good one".
MODEL_FALLBACK_CHAIN = ["gemini-flash-lite-latest", "gemini-flash-latest"]
DEFAULT_MODEL = MODEL_FALLBACK_CHAIN[0]

# Per-(model, key) attempt — no same-combination retry. Cycling to the
# next combination in the chain is strictly more useful than retrying an
# identical one: a 503 means *that model* is overloaded right now, and a
# second identical request a moment later is asking the same question
# rather than gathering new information the way trying a different model
# does. A genuine network blip (rare) still gets picked back up on retry
# because run_daily_ingestion-style callers can call generate() again;
# this module doesn't need to hide that from a single click.
_TOTAL_DEADLINE_SECONDS = 45.0
_CONNECT_TIMEOUT = 5.0
# Short enough that exhausting several combinations still fits the total
# budget above (up to 8 combinations at 2 models x 4 keys), long enough
# that a genuinely-generating (not hung) call isn't cut off mid-flight.
_READ_TIMEOUT = 15.0


class GeminiSummaryProvider:
    """Thin wrapper over the REST API (no SDK dependency, same style as
    app/providers/india/google_news.py's direct httpx use)."""

    name = "gemini_summary"

    def __init__(
        self,
        api_keys: list[str],
        *,
        models: list[str] = MODEL_FALLBACK_CHAIN,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_keys:
            raise ValueError("GeminiSummaryProvider needs at least one API key")
        self._api_keys = api_keys
        self._models = models
        self._client = client

    def generate(self, prompt: str) -> str:
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=5.0, pool=5.0
            )
        )
        deadline = time.monotonic() + _TOTAL_DEADLINE_SECONDS
        # Models outer, keys inner — see MODEL_FALLBACK_CHAIN's comment on
        # why. A model-overload failure is far more likely to be shared
        # across keys (both hit the same overloaded backend) than a
        # key-specific failure (quota, a bad key) is to be shared across
        # models, so cycling models first wastes fewer combinations on a
        # failure mode that repeats identically.
        combinations = [
            (model, key) for model in self._models for key in self._api_keys
        ]
        try:
            last_error: ProviderError | None = None
            for index, (model, api_key) in enumerate(combinations):
                remaining = deadline - time.monotonic()
                # Guaranteed at least one attempt regardless of the clock —
                # `index > 0` here, not just `remaining <= 0`, the same way
                # the single-combination version of this loop always ran
                # attempt 1 unconditionally. Without it, a deadline that's
                # already effectively spent by the time generate() is
                # called would break before last_error is ever set, and
                # the assert below would raise a bare AssertionError
                # instead of a real ProviderError.
                if index > 0 and remaining <= 0:
                    # Budget spent. Whatever the last failure was is the
                    # honest thing to report — inventing a "timed out
                    # overall" message would hide which call actually broke.
                    break
                try:
                    response = client.post(
                        API_URL.format(model=model),
                        # Header, not `params={"key": ...}` — see the
                        # module docstring's Bug 1. Works for every key
                        # type, so it's the right default regardless of
                        # which kind is configured.
                        headers={"x-goog-api-key": api_key},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=httpx.Timeout(
                            connect=_CONNECT_TIMEOUT,
                            read=min(_READ_TIMEOUT, max(remaining, 1.0)),
                            write=5.0,
                            pool=5.0,
                        ),
                    )
                except httpx.HTTPError as error:
                    last_error = ProviderError(
                        "gemini_summary", f"request failed: {error}", retryable=True
                    )
                    continue

                if response.status_code == 429:
                    # Per-key quota/rate limit — exactly the case a second
                    # key in the pool exists for. Move on rather than
                    # raising immediately (the old behavior, back when
                    # there was only ever one key to try).
                    last_error = ProviderError("gemini_summary", "rate limited", retryable=True)
                    continue
                if response.status_code != 200:
                    body = response.text[:500]
                    # Google returns a JSON error body for genuine problems
                    # (bad model, malformed request, overload). A 4xx with
                    # an *empty* body, on a model that models.list says
                    # supports generateContent, is Bug 1's exact signature
                    # — say so rather than reporting a bare status nobody
                    # can act on. See the module docstring for how to
                    # re-confirm.
                    if not body.strip() and 400 <= response.status_code < 500:
                        body = (
                            "empty response body — this key may need header auth "
                            "instead of a query param (see this module's docstring, "
                            "'Bug 1') rather than a console restriction"
                        )
                    last_error = ProviderError(
                        "gemini_summary",
                        f"generate failed: {response.status_code}: {body}",
                        retryable=response.status_code >= 500,
                    )
                    continue

                payload = response.json()
                try:
                    candidate = payload["candidates"][0]
                    return "".join(
                        part["text"] for part in candidate["content"]["parts"]
                    ).strip()
                except (KeyError, IndexError) as error:
                    # Gemini returns 200 with no candidates when its own
                    # safety filter blocks the output — a real, if rare,
                    # outcome, not a parsing bug, and not something any
                    # other (model, key) combination would answer
                    # differently, so this raises immediately rather than
                    # continuing the loop.
                    raise ProviderError("gemini_summary", "no summary in response") from error
            # Reachable only by exhausting every combination or the
            # deadline — and each iteration that doesn't return or raise
            # directly sets last_error first, so it's genuinely always set
            # here, mypy just can't see that across the loop.
            assert last_error is not None
            raise last_error
        finally:
            if owns_client:
                client.close()
