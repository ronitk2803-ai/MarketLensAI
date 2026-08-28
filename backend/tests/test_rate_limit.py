"""TokenBucketLimiter in isolation — no DB, no TestClient.

Follows the established time-based-throttle idiom (test_auth_codes_
service.py's back-dating pattern), adapted for in-memory state: this
module reads time.monotonic() rather than a DB timestamp, so tests
monkeypatch that clock directly instead of back-dating a row.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core import rate_limit as rl
from app.core.rate_limit import TokenBucketLimiter


def _fake_clock(monkeypatch: pytest.MonkeyPatch, start: float = 1000.0) -> list[float]:
    """A mutable [now] the test controls, patched into the module rate_limit
    actually calls time.monotonic() from — not into the stdlib globally,
    which would also perturb anything else using the real clock in the
    same process."""
    now = [start]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    return now


def test_a_zero_refill_rate_is_rejected_at_construction() -> None:
    """No registered limiter is ever configured this way, but a future typo
    (a limit expressed as N per 0 seconds) should fail loudly here rather
    than as a ZeroDivisionError on whichever request happens to exhaust the
    bucket first."""
    with pytest.raises(ValueError, match="positive"):
        TokenBucketLimiter(capacity=1, refill_per_second=0)


def test_a_burst_up_to_capacity_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=3, refill_per_second=1.0)

    assert [limiter.check("k")[0] for _ in range(3)] == [True, True, True]


def test_the_request_past_capacity_is_rejected_with_a_positive_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=3, refill_per_second=1.0)
    for _ in range(3):
        limiter.check("k")

    allowed, retry_after = limiter.check("k")

    assert allowed is False
    assert retry_after > 0


def test_waiting_past_one_refill_interval_succeeds_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=1.0)
    assert limiter.check("k")[0] is True
    assert limiter.check("k")[0] is False

    now[0] += 1.0  # exactly one refill interval later

    assert limiter.check("k")[0] is True


def test_partial_refill_is_not_enough_for_a_full_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the boundary the other way: refilling to just under one token
    must still reject — a >= 1 check with a < condition sneaking in would
    silently admit a request the bucket hasn't actually earned."""
    now = _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=1.0)
    limiter.check("k")

    now[0] += 0.99

    assert limiter.check("k")[0] is False


def test_two_different_keys_are_fully_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=1.0)

    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is False
    # "b" has never been seen — its own fresh bucket, unaffected by "a".
    assert limiter.check("b")[0] is True


def test_refill_never_exceeds_capacity_even_after_a_long_idle_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=2, refill_per_second=1.0)
    limiter.check("k")
    limiter.check("k")

    now[0] += 1000.0  # idle far longer than needed to refill

    # Capped at capacity=2, not 1000 tokens' worth of accumulated refill.
    assert [limiter.check("k")[0] for _ in range(2)] == [True, True]
    assert limiter.check("k")[0] is False


def test_concurrent_checks_never_let_more_than_capacity_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one test that actually exercises the lock: every route in this
    app is a sync def, so FastAPI runs them on a real threadpool, and
    concurrent requests for the same caller are concurrent OS threads —
    not just concurrent coroutines a single-threaded event loop could
    serialize for free."""
    _fake_clock(monkeypatch)
    # A vanishingly small (not zero — the constructor rejects that, see
    # test_a_zero_refill_rate_is_rejected_at_construction) refill rate:
    # over the fake clock frozen at one instant for this whole test, no
    # meaningful refill can occur regardless.
    limiter = TokenBucketLimiter(capacity=10, refill_per_second=1e-9)

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda _: limiter.check("k")[0], range(200)))

    assert sum(results) == 10


def test_sweep_drops_only_fully_refilled_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _fake_clock(monkeypatch)
    limiter = TokenBucketLimiter(capacity=2, refill_per_second=1.0)
    limiter.check("idle")  # 1 token left, will fully refill
    limiter.check("busy")
    limiter.check("busy")  # 0 tokens left, will NOT fully refill in 1s

    now[0] += 1.0

    dropped = limiter.sweep()

    assert dropped == 1
    assert "idle" not in limiter._buckets
    assert "busy" in limiter._buckets


def test_sweep_all_covers_every_registered_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_clock(monkeypatch)
    for limiter in rl._LIMITERS.values():
        limiter.check("stale-key-for-sweep-test")
        # Force each straight to "fully refilled" regardless of its own
        # refill rate, so the sweep is guaranteed to see something to drop
        # without hand-computing each limiter's specific window.
        limiter._buckets["stale-key-for-sweep-test"].tokens = float(limiter.capacity)

    dropped = rl.sweep_all()

    assert dropped >= len(rl._LIMITERS)
