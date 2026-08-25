"""Pure `list[Bar] -> float | None` metric helpers — no IO, no DB.

These exist so the two consumers of the metric registry can't drift: the
per-asset resolver (app/services/metric_registry.py, used by the nightly
thesis eval) and the batch resolver (app/services/screener.py, used to
scan the whole universe in one pass) both compute a metric here rather
than each implementing it. `test_metric_registry.py` asserts the two
paths return identical values for every registered key.

Every helper returns None rather than a guessed number when its inputs
are insufficient — the same "missing, never fabricated" contract
evaluate_trigger relies on to report "cannot evaluate" instead of a
false "not matched".
"""

from app.domain.models import Bar
from app.engines.indicators import (
    drawdown_series,
    historical_volatility,
    relative_volume,
    rsi,
    sma,
)


def latest_close(bars: list[Bar]) -> float | None:
    return bars[-1].close if bars else None


def dma_gap_pct(bars: list[Bar], period: int) -> float | None:
    """(close - dmaN) / dmaN * 100 — the exact formula
    app/engines/opportunity/screens.py's BelowDMA uses for `pct_below`, so
    "price below its 200DMA" is one scalar comparison
    (dma200_gap_pct lt 0) rather than a two-value one."""
    if not bars:
        return None
    closes = [b.close for b in bars]
    dma = sma(closes, period)[-1]
    if dma is None or dma == 0:
        return None
    return (closes[-1] - dma) / dma * 100


def change_pct(bars: list[Bar], period_days: int) -> float | None:
    """Percent change over the last `period_days` sessions — what
    DownOverPeriod computes, exposed as a metric so a user can pick their
    own threshold instead of being limited to the registry's frozen ones
    ("fell >20% in 30 days" is Screener.md's own example)."""
    if len(bars) <= period_days:
        return None
    start_close = bars[-(period_days + 1)].close
    # Matches DownOverPeriod's guard — a non-positive start price makes the
    # ratio meaningless, not merely extreme.
    if start_close <= 0:
        return None
    return (bars[-1].close - start_close) / start_close * 100


def rsi14(bars: list[Bar]) -> float | None:
    """Wilder's RSI is recursive from a seed at index 14 and only settles
    after roughly a hundred further bars, so this is only comparable to
    the company page's figure when fed a similarly long window — see the
    metric's `required_bars` in the registry."""
    if not bars:
        return None
    return rsi([b.close for b in bars], 14)[-1]


def volatility20(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    return historical_volatility([b.close for b in bars], window=20)[-1]


def drawdown_pct(bars: list[Bar]) -> float | None:
    """Percent below the running peak of the window (<= 0).

    Returned as a PERCENT, not the fraction drawdown_series produces.
    The fraction/percent split was a live inconsistency: the thesis metric
    registry exposed the raw fraction (-0.31) under the same name that
    scoring multiplied to a percent (-30.9), so a trigger typed as "-30"
    silently meant -3000%. Percent is canonical everywhere now.

    Window-dependent by construction (the peak is the window's peak), so
    the registry pins one window for it rather than letting a caller's
    lookback silently change what the metric means."""
    if not bars:
        return None
    series = drawdown_series([b.close for b in bars])
    return series[-1] * 100 if series else None


def relative_volume20(bars: list[Bar]) -> float | None:
    """Latest session's volume against its trailing 20-session average —
    the same figure UnusualVolume screens on."""
    if not bars:
        return None
    return relative_volume([b.volume for b in bars], window=20)[-1]


def delivery_pct(bars: list[Bar]) -> float | None:
    """Share of the latest session's volume that settled as delivery.
    Often absent (bhavcopy carries it, other sources don't)."""
    return bars[-1].delivery_pct if bars else None
