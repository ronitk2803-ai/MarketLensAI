"""Historical falls for one company's page (Build_plan.md §S.21).

Answers founder_vision.md's "has something similar happened before, and
what happened after?" — for THIS company against its own past, not against
other stocks. Screener.md:477-479 makes the boundary explicit: what comes
out is context, never a prediction.

Recomputed from bars on every request rather than cached in a
`historical_event` table. Not because caching would be hard, but because an
episode is not a stable fact: `recovered`/`recovery_date` change as bars
arrive, and a past fall's *magnitude* changes retroactively if a missing
split is later discovered and the whole series is re-adjusted. A cached row
would then quietly disagree with the chart directly above it on the same
page. Computing from bars keeps this consistent with /prices and
/technicals by construction.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.engines.historical.compare import (
    DEFAULT_COMPARABLE_LIMIT,
    Comparable,
    rank_comparables,
)
from app.engines.historical.episodes import (
    DEFAULT_MIN_DECLINE_PCT,
    Episode,
    detect_episodes,
)
from app.services.adjusted_prices import get_adjusted_bars

# Deliberately far longer than any history we hold, rather than a "5 year"
# window. get_price_history derives `start` from `today - lookback`, so a
# fixed 5-year lookback slides forward every day: an episode whose peak sits
# at the edge of the window would silently change magnitude, or vanish,
# overnight. For a feature whose entire claim is "here is what happened",
# the reported past must not move. Reading everything stored costs the same
# — PriceOHLCV's (asset_id, date) primary key covers it as one index range
# scan — and any on-demand refetch is clamped to the last 10 days regardless
# (prices.py MAX_ON_DEMAND_FETCH_DAYS).
FULL_HISTORY_LOOKBACK_DAYS = 365 * 25


@dataclass(frozen=True, slots=True)
class CurrentFall:
    """The open episode, plus the two things that are true only of an
    unfinished fall and would be misleading on `Episode` itself."""

    episode: Episode
    # PERCENT, negative: peak to the LATEST close. Distinct from the
    # episode's decline_pct (peak to trough) because a fall that has bounced
    # off its low has two honest numbers, not one.
    current_drawdown_pct: float
    # The lowest close so far IS the last bar — no bottom has formed yet, so
    # peak_to_trough_* is "how long it has been falling", not a settled
    # duration. Decided here rather than left for the frontend to infer from
    # matching dates: a disclosure rule shouldn't live in a template.
    trough_is_latest_bar: bool


@dataclass(frozen=True, slots=True)
class HistoricalFallsResult:
    as_of: dt.date | None
    history_start: dt.date | None
    min_decline_pct: float
    current: CurrentFall | None
    comparable: list[Comparable]
    past_count: int
    excluded_left_censored: int
    price_source: str


def _empty(price_source: str = "cache") -> HistoricalFallsResult:
    return HistoricalFallsResult(
        as_of=None,
        history_start=None,
        min_decline_pct=DEFAULT_MIN_DECLINE_PCT,
        current=None,
        comparable=[],
        past_count=0,
        excluded_left_censored=0,
        price_source=price_source,
    )


def get_historical_falls(
    db: Session,
    asset: Asset,
    *,
    min_decline_pct: float = DEFAULT_MIN_DECLINE_PCT,
    limit: int = DEFAULT_COMPARABLE_LIMIT,
) -> HistoricalFallsResult:
    # Same exclusion, and the same live-verified reason, as the universe
    # loader in opportunities.py: our corporate-actions source doesn't track
    # ETF unit consolidations, so one shows up as a ~90% crash that never
    # recovers. There are 41 active ETFs and _get_asset_or_404 doesn't
    # filter them out.
    if asset.asset_class != "EQUITY":
        return _empty()

    bars, price_source = get_adjusted_bars(db, asset, lookback_days=FULL_HISTORY_LOOKBACK_DAYS)
    if not bars:
        return _empty(price_source)

    episodes = detect_episodes(bars, min_decline_pct=min_decline_pct)
    latest = bars[-1]

    # detect_episodes guarantees at most one open episode and that it is
    # last, so this is the only place a "current" fall can be.
    current: CurrentFall | None = None
    past = episodes
    if episodes and not episodes[-1].recovered:
        open_episode = episodes[-1]
        past = episodes[:-1]
        current = CurrentFall(
            episode=open_episode,
            current_drawdown_pct=(latest.close - open_episode.peak_close)
            / open_episode.peak_close
            * 100,
            trough_is_latest_bar=open_episode.trough_date == latest.date,
        )

    comparison = rank_comparables(
        current.episode if current is not None else None, past, limit=limit
    )
    return HistoricalFallsResult(
        as_of=latest.date,
        history_start=bars[0].date,
        min_decline_pct=min_decline_pct,
        current=current,
        comparable=comparison.comparable,
        past_count=comparison.past_count,
        excluded_left_censored=comparison.excluded_left_censored,
        price_source=price_source,
    )
