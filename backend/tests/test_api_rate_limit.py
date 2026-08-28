"""Rate limiting exercised through real HTTP requests.

TokenBucketLimiter's own correctness (refill math, concurrency, sweeping)
is covered in test_rate_limit.py. This file only checks the wiring: that
the right routes are actually gated, that a 429 carries Retry-After and
still gets CORS headers, and that the one route which must never surface a
429 (password-reset/request) doesn't.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import rate_limit as rl
from app.core.rate_limit import _LIMITERS
from app.db.session import get_db
from app.main import app
from tests.helpers import auth_headers

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freezes time.monotonic() for the rate limiter specifically.

    Several tested routes do real work (a screener run, a universe scan)
    that takes hundreds of milliseconds per call. Left on the real clock, a
    capacity+1 loop of slow requests lets meaningful refill accumulate
    DURING the test itself — verified live: /opportunities's 20-capacity
    bucket, refilling at 20/60 per second, absorbed ~5 extra tokens over a
    ~15s loop of real requests, so 21 real calls never actually exhausted
    it. Freezing the clock makes the test depend only on request COUNT,
    not on how long each request happens to take on this machine.
    """
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1_000_000.0)


def test_screener_run_429s_after_capacity_and_carries_retry_after(_frozen_clock: None) -> None:
    headers = auth_headers("ratelimit-screener")
    capacity = _LIMITERS["screener_run"].capacity
    body = {
        "tree": {"op": "and", "children": [{"metric": "close", "operator": "gt", "threshold": 0}]}
    }

    responses = [
        client.post("/api/v1/screener/run", json=body, headers=headers)
        for _ in range(capacity + 1)
    ]

    assert [r.status_code for r in responses[:capacity]] == [200] * capacity
    last = responses[-1]
    assert last.status_code == 429
    assert "Retry-After" in last.headers
    assert int(last.headers["Retry-After"]) > 0
    assert last.json()["detail"] == "too many requests — try again shortly"


def test_screener_run_limit_is_per_user_not_shared(_frozen_clock: None) -> None:
    """Two different signed-in users must not share one budget — the key is
    user_id, not something coarser like "authenticated requests"."""
    capacity = _LIMITERS["screener_run"].capacity
    alice = auth_headers("ratelimit-alice")
    bob = auth_headers("ratelimit-bob")
    body = {
        "tree": {"op": "and", "children": [{"metric": "close", "operator": "gt", "threshold": 0}]}
    }

    for _ in range(capacity):
        assert client.post("/api/v1/screener/run", json=body, headers=alice).status_code == 200

    # Alice is now exhausted...
    assert client.post("/api/v1/screener/run", json=body, headers=alice).status_code == 429
    # ...but Bob has his own untouched bucket.
    assert client.post("/api/v1/screener/run", json=body, headers=bob).status_code == 200


def test_opportunities_is_rate_limited_by_ip_independent_of_auth(_frozen_clock: None) -> None:
    """/opportunities stays public — no auth dependency here at all, only a
    rate limit. TestClient's requests all share one fixed client IP, so
    capacity+1 anonymous hits is enough to trip it regardless of whether
    any of them carried a token."""
    capacity = _LIMITERS["opportunities"].capacity

    responses = [
        client.get("/api/v1/opportunities", params={"screen": "down_5d"})
        for _ in range(capacity + 1)
    ]

    assert responses[-1].status_code == 429
    # Never gained an auth requirement as a side effect of adding the limiter.
    assert responses[0].status_code != 401


def test_a_tier_d_route_is_covered_only_by_the_global_backstop(_frozen_clock: None) -> None:
    """Watchlist CRUD has no dedicated limiter — confirm it survives well
    past any Tier A/C capacity, and is bounded only by the much looser
    global ceiling."""
    headers = auth_headers("ratelimit-tierD")
    tightest_tier_capacity = min(
        limiter.capacity for name, limiter in _LIMITERS.items() if name != "global"
    )

    responses = [
        client.get("/api/v1/watchlist", headers=headers)
        for _ in range(tightest_tier_capacity + 5)
    ]

    assert all(r.status_code == 200 for r in responses)


def test_password_reset_request_stays_200_even_once_its_limiter_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one route where a 429 would itself be the leak: any status other
    than 200 says whether the address is registered. Stubs send_code so
    this never touches Resend."""
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "send_code", lambda db, user, purpose: None)
    capacity = _LIMITERS["password_reset_request"].capacity

    responses = [
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "nobody-in-particular@example.com"},
        )
        for _ in range(capacity + 3)
    ]

    assert all(r.status_code == 200 for r in responses)
    assert all(r.json() == {"status": "ok"} for r in responses)


def test_register_is_rate_limited_by_ip(_frozen_clock: None) -> None:
    from uuid import uuid4

    capacity = _LIMITERS["auth_register"].capacity

    responses = [
        client.post(
            "/api/v1/auth/register",
            json={
                "email": f"ratelimit-reg-{uuid4().hex[:8]}@example.com",
                "password": "password123",
            },
        )
        for _ in range(capacity + 1)
    ]

    assert [r.status_code for r in responses[:capacity]] == [200] * capacity
    assert responses[-1].status_code == 429


def test_a_429_still_carries_cors_headers(_frozen_clock: None) -> None:
    """Confirms the middleware ordering in app/main.py: RateLimitMiddleware
    is added BEFORE CORSMiddleware, so CORS stays outermost and still
    attaches its headers to a 429 the rate limiter short-circuits. Added on
    the wrong side, this response would have no Access-Control-Allow-Origin
    header and a browser would report an opaque network error instead of a
    readable 429."""
    capacity = _LIMITERS["opportunities"].capacity
    for _ in range(capacity):
        client.get(
            "/api/v1/opportunities",
            params={"screen": "down_5d"},
            headers={"Origin": "http://localhost:3000"},
        )

    limited = client.get(
        "/api/v1/opportunities",
        params={"screen": "down_5d"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert limited.status_code == 429
    assert limited.headers.get("access-control-allow-origin") == "http://localhost:3000"
