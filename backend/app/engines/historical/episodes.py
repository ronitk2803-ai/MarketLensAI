"""Peak -> trough -> recovery episodes in one company's own price history.

Pure, no IO. The unit of analysis is an *underwater episode*: the stretch
between a running-peak close and the first close back at or above it. That
definition is deliberate — it is the only one where "recovered" means what
a holder actually experienced (the price got back to where they bought at
the top), and it needs no arbitrary window, unlike a rolling drawdown whose
peak moves with the caller's lookback.

Units are load-bearing here and stated in every field comment: `*_pct` is a
PERCENT (never a fraction), `fall_volatility` is a FRACTION (matching
TechnicalSnapshot.volatility20, which the same page renders), `*_days` are
CALENDAR days and `*_sessions` are bars. The percent/fraction split has
already been a live bug twice in this codebase (see
app/engines/opportunity/metrics.py:79-82).
"""

import datetime as dt
import statistics
from dataclasses import dataclass

from app.domain.models import Bar
from app.engines.indicators.volatility import TRADING_DAYS_PER_YEAR, daily_returns

# The conventional "bear market" line, and the same threshold the down_90d
# screen already uses (app/engines/opportunity/registry.py). Expressed as a
# POSITIVE magnitude, matching DownOverPeriod's min_decline_pct convention,
# and compared against the negative decline_pct.
DEFAULT_MIN_DECLINE_PCT = 20.0

# Below this many daily returns, a stdev is arithmetic rather than a
# meaningful volatility estimate — report None instead of a number that
# looks like one ("missing, never fabricated").
_MIN_RETURNS_FOR_VOLATILITY = 10


@dataclass(frozen=True, slots=True)
class Episode:
    """One completed or still-open fall, measured on adjusted closes."""

    peak_date: dt.date
    peak_close: float  # INR, corporate-action adjusted
    trough_date: dt.date  # FIRST date the episode's lowest close was reached
    trough_close: float  # INR, adjusted
    recovery_date: dt.date | None  # first close >= peak_close; None while open
    recovery_close: float | None  # INR; >= peak_close by construction
    decline_pct: float  # PERCENT and NEGATIVE: (trough - peak) / peak * 100
    peak_to_trough_days: int  # CALENDAR days
    peak_to_trough_sessions: int  # BARS
    trough_to_recovery_days: int | None  # CALENDAR days; None while open
    trough_to_recovery_sessions: int | None  # BARS; None while open
    fall_volatility: float | None  # FRACTION, annualized, over peak..trough
    worst_session_pct: float  # PERCENT and NEGATIVE: worst single day in the fall
    worst_session_date: dt.date  # its date — the tell for an unadjusted action
    recovered: bool
    # The peak is the first bar we hold, so the fall was already underway
    # when this history begins: decline_pct is a LOWER BOUND and peak_date
    # is a window edge, not an observed peak.
    left_censored: bool


def _annualized_volatility(closes: list[float]) -> float | None:
    """Stdev of the daily returns *inside* this fall leg, annualized.

    Deliberately not indicators.historical_volatility: its rolling 20-day
    window would both pull in returns from before the peak and return None
    for every leg shorter than 21 closes — and short, violent falls are
    exactly the ones worth reporting a volatility for.
    """
    returns = daily_returns(closes)
    if len(returns) < _MIN_RETURNS_FOR_VOLATILITY:
        return None
    return statistics.stdev(returns) * TRADING_DAYS_PER_YEAR**0.5


def _worst_session(bars: list[Bar], peak_i: int, trough_i: int) -> tuple[float, dt.date]:
    """Largest single-session drop between the peak and the trough, as a
    negative percent. `trough_i > peak_i` always, so there is at least one
    session to measure."""
    worst_pct = 0.0
    worst_date = bars[trough_i].date
    for i in range(peak_i + 1, trough_i + 1):
        change = (bars[i].close - bars[i - 1].close) / bars[i - 1].close * 100
        if change < worst_pct:
            worst_pct, worst_date = change, bars[i].date
    return worst_pct, worst_date


def _build_episode(
    bars: list[Bar], peak_i: int, trough_i: int, recovery_i: int | None
) -> Episode:
    peak, trough = bars[peak_i], bars[trough_i]
    recovery = bars[recovery_i] if recovery_i is not None else None
    worst_pct, worst_date = _worst_session(bars, peak_i, trough_i)
    return Episode(
        peak_date=peak.date,
        peak_close=peak.close,
        trough_date=trough.date,
        trough_close=trough.close,
        recovery_date=recovery.date if recovery is not None else None,
        recovery_close=recovery.close if recovery is not None else None,
        decline_pct=(trough.close - peak.close) / peak.close * 100,
        peak_to_trough_days=(trough.date - peak.date).days,
        peak_to_trough_sessions=trough_i - peak_i,
        # None, never "days so far": a fall that hasn't recovered has no
        # recovery duration, and reporting the elapsed time in that field
        # would let a still-falling stock read as a slow recovery.
        trough_to_recovery_days=(recovery.date - trough.date).days if recovery else None,
        trough_to_recovery_sessions=(recovery_i - trough_i) if recovery_i is not None else None,
        fall_volatility=_annualized_volatility([b.close for b in bars[peak_i : trough_i + 1]]),
        worst_session_pct=worst_pct,
        worst_session_date=worst_date,
        recovered=recovery is not None,
        left_censored=peak_i == 0,
    )


def detect_episodes(
    bars: list[Bar], *, min_decline_pct: float = DEFAULT_MIN_DECLINE_PCT
) -> list[Episode]:
    """Every fall of `min_decline_pct` or more, ascending by peak date.

    `bars` must be adjusted closes in ascending date order (never sorted
    here — a caller passing them unsorted has an upstream bug worth
    surfacing, not papering over).

    At most one returned episode is still open, and it is necessarily the
    last: an open episode is only closed out by a new peak, which is also
    where the next one can begin.

    The `<` to open and `>=` to close is not a typo. Opening on `<=` would
    start a phantom episode on the second bar of a flat series that could
    never close; closing on `>` would mean returning to exactly the old
    high didn't count as getting back to it.
    """
    # A non-positive close makes every ratio here meaningless rather than
    # merely extreme — the same guard, for the same reason, as
    # opportunity/metrics.py's change_pct. Never read a 0 as a -100% trough.
    usable = [bar for bar in bars if bar.close > 0]
    if len(usable) < 2:
        return []

    episodes: list[Episode] = []
    peak_i = 0
    trough_i = 0
    is_open = False

    for i in range(1, len(usable)):
        close = usable[i].close
        if not is_open:
            if close >= usable[peak_i].close:
                peak_i = i
            else:
                is_open, trough_i = True, i
            continue
        # `<` not `<=`: the FIRST time the bottom was reached is the trough,
        # which makes trough-to-recovery the longer, conservative reading.
        if close < usable[trough_i].close:
            trough_i = i
        if close >= usable[peak_i].close:
            episode = _build_episode(usable, peak_i, trough_i, i)
            if episode.decline_pct <= -min_decline_pct:
                episodes.append(episode)
            peak_i, is_open = i, False

    if is_open:
        episode = _build_episode(usable, peak_i, trough_i, None)
        # The threshold applies to the open episode too: a stock less than
        # `min_decline_pct` off its high is not having an event.
        if episode.decline_pct <= -min_decline_pct:
            episodes.append(episode)

    return episodes
