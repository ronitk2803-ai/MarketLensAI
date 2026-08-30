"""Rate limiting — the first in this app. Every layer was unthrottled until
now (screener.py and companies.py's ai-summary docstrings both said so out
loud), which was fine on localhost and stops being fine the moment there's
a public URL.

In-memory, not DB-backed, and deliberately so. docker-compose.prod.yml runs
exactly one backend service with no scaling directive, and Deployment.md
frames Render/Fly as single always-on web services throughout — the same
deployment shape app/services/quotes.py's CACHE_TTL cache and
UpstoxTokenManager already built in-memory state for. A DB-backed limiter
would mean every request, including trivial CRUD, pays a write purely for
bookkeeping with zero value once a window rolls over — worse than the thing
being limited. The one thing a DB survives that memory doesn't (a restart
mid-abuse) is a bounded, self-healing gap, not a real vector. It also means
this module has no db.commit() anywhere, which sidesteps an entire category
of bug company_summary.py and auth_codes.py both had to learn the hard way:
a flushed-only row vanishes when get_db rolls back a raised exception — "a
limit that never persists is not a limit." Nothing here can have that bug,
because nothing here is ever rolled back.

Token bucket, not fixed-window (allows up to 2x the intended rate across a
window boundary) or a sliding-window log (O(requests-in-window) memory and
work per key). A bucket is two numbers per key, O(1) to check, with no
boundary artifact — a burst is capped at `capacity` regardless of when it
lands relative to any clock tick.

Two layers, because they protect different things:
- The global backstop (RateLimitMiddleware, every route) catches
  undifferentiated volume from one caller across arbitrary routes — no
  single route looks abusive in isolation. This is exactly the shape of
  the runaway-prefetch-loop incident this app already had once (a
  same-origin JS bug, not malicious traffic, but the identical symptom).
- Tier-specific limits (the `rate_limited` Depends() factory, applied only
  to the handful of routes that actually spend something — a full
  universe scan, an LLM call, an outbound email) need a far tighter
  ceiling than any single global number could set without also pinching
  ordinary watchlist/thesis/portfolio CRUD.
"""

import threading
import time
from dataclasses import dataclass
from math import ceil

from fastapi import Depends, HTTPException, Request
from fastapi.params import Depends as DependsType
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.services.auth import decode_access_token


@dataclass
class _Bucket:
    tokens: float
    last_refill: float  # time.monotonic() — never datetime.now(): this
    # module never compares a timestamp across a process restart, so it
    # only needs a clock that can't jump backwards (NTP step, DST, a
    # manual clock change), which monotonic guarantees and wall-clock time
    # does not.


class TokenBucketLimiter:
    """A named token bucket per caller key.

    `threading.Lock()` for the same reason quotes.py's cache needs one:
    every route in this app is a sync `def`, so FastAPI runs them on a
    real threadpool — concurrent requests are concurrent OS threads, not
    just concurrent coroutines. Held only across the O(1) refill-and-check
    arithmetic below, never across I/O.
    """

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        if refill_per_second <= 0:
            # Every registered limiter (below) has a positive rate, so this
            # never fires from real config — it exists so a future typo
            # (e.g. a limit expressed as N per 0 seconds) fails loudly at
            # construction instead of as a ZeroDivisionError on whichever
            # request happens to exhaust the bucket first.
            raise ValueError("refill_per_second must be positive")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        """Advances one bucket to `now`. Caller must hold `self._lock`.
        Shared by check() and sweep() so both agree on one definition of
        "how full is this bucket right now" — sweep() reading `bucket.
        tokens` directly, without this step, would only ever see the
        stale value left over from that key's last check() call, so an
        idle-but-not-yet-fully-refilled bucket (still holding whatever
        deficit its last request incurred, from a request that may have
        been minutes ago) would never look "full enough to drop" no
        matter how long it actually sat idle.
        """
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
        bucket.last_refill = now

    def check(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds). The second value is the
        wait until one token will be available — meaningful only when the
        first is False."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.capacity), last_refill=now)
                self._buckets[key] = bucket
            else:
                self._refill_locked(bucket, now)
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0.0
            deficit = 1 - bucket.tokens
            return False, deficit / self.refill_per_second

    def sweep(self) -> int:
        """Drops every bucket sitting at full capacity — idle long enough
        to have fully refilled, so a fresh bucket and a full one behave
        identically going forward and nothing is lost by dropping it.

        Needed because, unlike quotes.py's cache (keyed on a small, bounded,
        constantly-reused symbol set), this is keyed on CALLER — unbounded
        and adversarial, since any public endpoint lets anyone mint a fresh
        key just by making one request from a new IP. Lazy per-key refill
        alone would let that dict grow forever. Returns the count dropped,
        for logging.
        """
        now = time.monotonic()
        with self._lock:
            for bucket in self._buckets.values():
                self._refill_locked(bucket, now)
            stale = [key for key, bucket in self._buckets.items() if bucket.tokens >= self.capacity]
            for key in stale:
                del self._buckets[key]
            return len(stale)


# One registry rather than scattered module globals, so sweeping and
# reasoning about "every limiter that exists" both have one place to look.
# Numbers here are a starting point, sized against this app's own measured
# shape (see each Depends(rate_limited(...)) call site for the specific
# reasoning) — not a final answer; revisit after real traffic.
_LIMITERS: dict[str, TokenBucketLimiter] = {
    "global": TokenBucketLimiter(capacity=60, refill_per_second=60 / 60),
    "screener_run": TokenBucketLimiter(capacity=3, refill_per_second=3 / 3600),
    "opportunities": TokenBucketLimiter(capacity=20, refill_per_second=20 / 60),
    "ai_summary": TokenBucketLimiter(capacity=5, refill_per_second=5 / 86400),
    # Tighter than ai_summary's per-day cap looks, not looser: one question
    # here can be several Gemini calls (research_assistant.py's tool-calling
    # loop, up to MAX_TOOL_CALLS turns, each with its own model/key fallback
    # sweep), so the actual generation cost per request is materially
    # higher than one ai-summary click.
    "nl_assistant": TokenBucketLimiter(capacity=10, refill_per_second=10 / 86400),
    "quotes": TokenBucketLimiter(capacity=30, refill_per_second=30 / 60),
    "auth_register": TokenBucketLimiter(capacity=5, refill_per_second=5 / 3600),
    "auth_login": TokenBucketLimiter(capacity=10, refill_per_second=10 / 60),
    "password_reset_request": TokenBucketLimiter(capacity=5, refill_per_second=5 / 3600),
}


def reset_all() -> None:
    """Clears every limiter's bucket state. Production never calls this —
    it exists for tests.

    `_LIMITERS` is a module-level global, so every request across the
    entire test process shares it, the same as it does in a real running
    server. Without a reset between tests, the existing suites that
    legitimately call /auth/register, /auth/login, /screener/run,
    /opportunities, /quotes, and /ai-summary many times each (32+ call
    sites across tests/test_api_*.py, verified by grep before this module
    had any limiter to trip) would start failing partway through a run —
    not because anything they test is wrong, but because an EARLIER,
    unrelated test already spent that key's budget. tests/conftest.py's
    autouse fixture calls this before every test function, giving rate
    limiting the same per-test isolation the `db` fixture's rollback
    already gives the database.
    """
    for limiter in _LIMITERS.values():
        limiter._buckets.clear()


def sweep_all() -> int:
    """Called on an hourly schedule from app.main's lifespan, unconditionally
    — not gated behind settings.enable_scheduler the way daily_ingestion is.
    Ingestion is optional batch work; an unbounded dict is a memory-safety
    concern that shouldn't be opt-in on a public deploy."""
    return sum(limiter.sweep() for limiter in _LIMITERS.values())


def _client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The RIGHTMOST entry, not the leftmost. Render/Fly sit as
            # exactly one hop in front of this container (no nested
            # backend-facing CDN in this deploy shape), and a trusted
            # single proxy APPENDS the real client IP as the last hop
            # before forwarding — so a client who pre-populates this
            # header with fake entries of their own has them land to the
            # LEFT of the proxy's own append, never displacing it.
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    if request.client is not None:
        return request.client.host
    return "unknown"


def resolve_caller_key(request: Request) -> str:
    """`user:<id>` for a validly-signed access token, else `ip:<address>`.

    Reuses decode_access_token (app/services/auth.py) rather than
    re-parsing the JWT — it already does signature/expiry checks with no
    DB hit, the right property for something called on every request
    including the global backstop. A forged Authorization header just
    fails to decode and falls through to IP keying like anyone else —
    there's no way to spoof a BETTER key than your own IP this way, only
    a worse one.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        user_id = decode_access_token(auth.removeprefix("Bearer "))
        if user_id is not None:
            return f"user:{user_id}"
    return f"ip:{_client_ip(request)}"


def _rate_limit_body(retry_after: float) -> tuple[dict[str, str], dict[str, str]]:
    seconds = str(max(1, ceil(retry_after)))
    return {"detail": "too many requests — try again shortly"}, {"Retry-After": seconds}


def rate_limited(name: str) -> DependsType:
    """A Depends() factory for the tier-specific limiters.

    Always keys via resolve_caller_key(request) — deliberately NOT passed
    a `user_id` parameter for FastAPI to fill in. A plain typed parameter
    with a default is exactly the shape FastAPI reads as a spoofable query
    param (`?user_id=999`), and threading the real value through would
    mean either duplicating this dependency per-route with a different
    signature, or depending on get_current_user a second time — needless
    complexity, because there's nothing to thread. screener_run and
    ai_summary already require a valid Bearer token via their own separate
    Depends(get_current_user)/get_current_verified_user before the route
    body runs, and resolve_caller_key independently decodes that SAME
    Authorization header (decode_access_token, no DB hit, cheap to call
    twice) — so it already resolves to `user:<id>` on those routes for
    free, with no coordination needed. Public routes (opportunities,
    auth_register, auth_login) simply have no token to decode and fall
    through to the IP path, which is exactly what they need.

    Raises 429 with Retry-After — except password_reset_request, whose
    endpoint deliberately does NOT use this dependency at all (see
    app/api/v1/auth.py): that route must stay 200 always, since a 429
    would answer "is this address registered" through response shape,
    exactly what its always-200 design exists to prevent. Its throttle is
    checked and swallowed manually instead.
    """
    limiter = _LIMITERS[name]

    def dependency(request: Request) -> None:
        key = resolve_caller_key(request)
        allowed, retry_after = limiter.check(key)
        if not allowed:
            detail, headers = _rate_limit_body(retry_after)
            raise HTTPException(status_code=429, detail=detail["detail"], headers=headers)

    return Depends(dependency)


def is_allowed(name: str, request: Request) -> bool:
    """Checks a tier limiter WITHOUT raising — for the one route that must
    never surface a 429: POST /auth/password-reset/request. That endpoint
    already returns 200 unconditionally regardless of whether the address
    exists, is throttled, or the email provider is down (see
    app/api/v1/auth.py's docstring) — any other answer states whether the
    address is registered. A 429 would be exactly that leak, through
    response shape instead of content. The route calls this and silently
    skips sending when it returns False, exactly as it already does for a
    CodeThrottled from the per-address auth_codes.py throttle.
    """
    allowed, _retry_after = _LIMITERS[name].check(resolve_caller_key(request))
    return allowed


class RateLimitMiddleware(BaseHTTPMiddleware):
    """The global backstop — every route, no opt-in required.

    Registered in app.main BEFORE app.add_middleware(CORSMiddleware, ...).
    Starlette wraps middleware in reverse of add_middleware call order, so
    whichever is added LAST ends up OUTERMOST. CORS must stay outermost so
    it still attaches CORS headers to a 429 this middleware returns —
    added on the wrong side, a 429 from the inner layer never reaches
    CORSMiddleware and arrives at a browser as an opaque, unreadable
    network error rather than a readable 429.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        limiter = _LIMITERS["global"]
        key = resolve_caller_key(request)
        allowed, retry_after = limiter.check(key)
        if not allowed:
            detail, headers = _rate_limit_body(retry_after)
            return JSONResponse(status_code=429, content=detail, headers=headers)
        return await call_next(request)
