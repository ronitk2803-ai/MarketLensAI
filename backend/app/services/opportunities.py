"""Runs Layer 1 opportunity screens against stored data only — no live
provider fetch per asset (Build_plan.md §K: "runs entirely against stored
data → fast, no live API storms"). Corporate-action adjustment uses
whatever's already in `corporate_action`; it does not lazily fetch (that
would turn one screen run into N live calls, defeating the point).
"""

import datetime as dt
import threading
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Asset, Company, Industry, PriceOHLCV, Score
from app.domain.models import AssetRef, Bar
from app.engines.adjustment import adjust_bars
from app.engines.opportunity.base import Hit
from app.engines.opportunity.ranking import RankedHit, apply_attention_ranking
from app.engines.opportunity.registry import SCREENS
from app.services.corporate_actions import get_stored_corporate_actions_bulk

# Rows are streamed from the server in batches rather than buffered whole.
# Sized to keep the round-trip count irrelevant (~100 batches for the widest
# screen) without holding a meaningful slice of the universe in the driver.
_STREAM_BATCH = 1000


def load_universe_bars_with_ids(
    db: Session, lookback_days: int, *, asset_ids: set[int] | None = None
) -> tuple[dict[AssetRef, list[Bar]], dict[AssetRef, int]]:
    """Same as _load_universe_bars, but also hands back each AssetRef's
    row id. AssetRef is a provider-agnostic value object with no id on it
    (app/domain/models.py), so a caller that needs to query another table
    keyed by asset_id — the screener's bulk ratio read — has no way to get
    there from the universe dict alone.

    `asset_ids` narrows the load to specific assets (the alert job only
    cares about watchlisted ones). Callers with a narrow set should still
    come through here rather than hand-rolling a query: the value isn't
    the row count, it's that this applies corporate-action adjustment. A
    loader that skipped it would report a fabricated -50% "price move" on
    every split day."""
    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    filters = [
        PriceOHLCV.date >= cutoff,
        Asset.active.is_(True),
        # ETFs slipped into the "EQ" universe (verified live — an ETF
        # unit consolidation showed as a false ~90% crash since our
        # corporate-actions source doesn't track it as a stock split);
        # screens are only meaningful for real listed equities.
        Asset.asset_class == "EQUITY",
    ]
    if asset_ids is not None:
        if not asset_ids:
            return {}, {}
        filters.append(Asset.id.in_(asset_ids))

    # Columns, not entities — and emphatically not `db.query(PriceOHLCV,
    # Asset)`. Hydrating an ORM instance per bar cost a measured 3.47 KB
    # against 1.73 KB for the plain tuple, because each instance carries its
    # own __dict__, Decimal objects for five Numeric columns, and an entry
    # in the Session identity map that keeps the whole result alive. On the
    # hosted universe below_dma200 (306 days, ~103k bars) that was ~350 MB
    # of the 512 MB Render instance for ONE request, and the homepage fires
    # four screens concurrently — the box was OOM-killed (exit 137).
    # SUMMARISER.md §8.6.
    #
    # Bars are built while the result streams and the tuple is dropped
    # immediately, so the raw rows and the Bar objects are never both fully
    # resident.
    # The Asset join stays (the filters above are on it) but NONE of its
    # columns are selected here. They used to be, which meant symbol,
    # exchange, market and name — ~40 bytes of the ~180-byte row — were
    # re-transmitted on every one of an asset's ~200 bars to build an
    # AssetRef that is identical across all of them. Postgres does not
    # deduplicate that; it is paid per row, on the wire, every request.
    # The identity columns are fetched once per asset below instead.
    stmt = (
        select(
            PriceOHLCV.asset_id,
            PriceOHLCV.date,
            PriceOHLCV.open,
            PriceOHLCV.high,
            PriceOHLCV.low,
            PriceOHLCV.close,
            PriceOHLCV.volume,
            PriceOHLCV.oi,
            PriceOHLCV.delivery_qty,
            PriceOHLCV.delivery_pct,
        )
        .join(Asset, Asset.id == PriceOHLCV.asset_id)
        .where(*filters)
        .order_by(PriceOHLCV.asset_id, PriceOHLCV.date)
        .execution_options(yield_per=_STREAM_BATCH)
    )

    bars_by_asset: dict[int, list[Bar]] = {}
    for row in db.execute(stmt):
        bars = bars_by_asset.get(row.asset_id)
        if bars is None:
            bars = bars_by_asset[row.asset_id] = []
        # float() at the boundary, matching services/prices.py's row_to_bar —
        # Bar is a float-valued domain object and the engines do arithmetic
        # on it. Kept in step with that function by hand; it takes an ORM
        # instance and this takes a column tuple, so neither can call the
        # other without giving back what this change bought.
        bars.append(
            Bar(
                date=row.date,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=row.volume,
                oi=row.oi,
                delivery_qty=row.delivery_qty,
                delivery_pct=float(row.delivery_pct) if row.delivery_pct is not None else None,
            )
        )

    # One row per asset that actually returned bars, rather than one per
    # bar. ~500 rows against the ~28,000 the join used to carry them on.
    asset_refs: dict[int, AssetRef] = {}
    if bars_by_asset:
        for asset_row in db.execute(
            select(Asset.id, Asset.symbol, Asset.exchange, Asset.market, Asset.name).where(
                Asset.id.in_(list(bars_by_asset))
            )
        ):
            asset_refs[asset_row.id] = AssetRef(
                symbol=asset_row.symbol,
                exchange=asset_row.exchange,
                market=asset_row.market,
                name=asset_row.name,
            )

    # One query for every asset's actions rather than one per asset: this
    # loop covers the whole active universe, so the per-asset version was
    # ~500 round trips per screen run — and the homepage runs four screens
    # concurrently.
    #
    # `since=cutoff` is not a heuristic. adjust_bars only applies a factor
    # whose ex_date is strictly after the bar it is adjusting, and no bar
    # here predates `cutoff`, so an action on or before it cannot change a
    # single output value. Without it this shipped the entire
    # `corporate_action` table (15,591 rows on the hosted universe) on
    # every screen run — four times over on one homepage render — to use
    # the handful that fall inside the window.
    actions_by_asset = get_stored_corporate_actions_bulk(db, list(bars_by_asset), since=cutoff)

    universe: dict[AssetRef, list[Bar]] = {}
    ids: dict[AssetRef, int] = {}
    # pop(), not iteration: adjust_bars returns a new list, so keeping the
    # raw one referenced would hold two full copies of the universe at the
    # moment of peak usage. Draining as we go caps it at one plus the asset
    # currently being adjusted.
    for asset_id in list(bars_by_asset):
        raw_bars = bars_by_asset.pop(asset_id)
        ref = asset_refs[asset_id]
        universe[ref] = adjust_bars(raw_bars, actions_by_asset.get(asset_id, []))
        ids[ref] = asset_id
    return universe, ids


def _load_universe_bars(db: Session, lookback_days: int) -> dict[AssetRef, list[Bar]]:
    universe, _ = load_universe_bars_with_ids(db, lookback_days)
    return universe


# NSE trades ~246 days a year, so a calendar window is only ~0.67 as many
# sessions. Converting with the inverse of that, plus a margin for the way
# holidays cluster (Diwali, year-end), keeps a screen from being starved of
# the sessions it needs at the exact moment it matters.
_TRADING_DAYS_PER_YEAR = 246
_CALENDAR_PER_TRADING_DAY = 365 / _TRADING_DAYS_PER_YEAR
_LOOKBACK_MARGIN_DAYS = 10


def calendar_lookback_for(required_bars: int) -> int:
    """Calendar days to request in order to get `required_bars` sessions."""
    return int(required_bars * _CALENDAR_PER_TRADING_DAY) + _LOOKBACK_MARGIN_DAYS


# Sessions of closing price behind each hit's sparkline. 30 is about a
# trading month — enough to read the shape that produced the hit without
# making the payload compete with the numbers beside it.
SPARKLINE_SESSIONS = 30


def _evaluate(
    db: Session,
    screen_id: str,
    *,
    lookback_days: int | None = None,
    min_bars: int = 0,
) -> tuple[list[Hit], dict[AssetRef, list[Bar]]]:
    """Run one screen and hand back the universe it ran against.

    Callers that need the underlying series (sparklines) would otherwise
    have to re-query and re-adjust every hit's bars, which is the same work
    the screen just did.
    """
    screen = SCREENS.get(screen_id)
    if screen is None:
        raise ValueError(f"unknown screen: {screen_id!r}")
    # Sized from the screen's own requirement rather than a flat default.
    # The old 120-calendar-day default is only ~82 sessions, so below_dma100
    # and below_dma200 were listed in the UI but could never return a hit —
    # sma() stays None until its window is full (verified live against a
    # fully backfilled universe: 1137 hits for below_dma50, 0 for both of
    # the others).
    if lookback_days is None:
        lookback_days = calendar_lookback_for(max(screen.required_bars, min_bars))
    universe = _load_universe_bars(db, lookback_days)
    return screen.evaluate(universe), universe


def run_screen(db: Session, screen_id: str, *, lookback_days: int | None = None) -> list[Hit]:
    hits, _ = _evaluate(db, screen_id, lookback_days=lookback_days)
    return hits


def _load_stored_scores(
    db: Session, assets: set[AssetRef]
) -> dict[str, tuple[float | None, float | None]]:
    """Latest stored Score per asset — read-only, no compute (Layer 2 stays
    "runs entirely against stored data" just like Layer 1). An asset with no
    Score row yet (nobody has viewed its company page, which is what
    triggers computation — see services/scoring.py) simply has no entry;
    the caller treats that as "unscored", not zero."""
    if not assets:
        return {}
    symbols = {a.symbol for a in assets}
    rows = (
        db.query(Asset.symbol, Asset.exchange, Score.value, Score.coverage, Score.as_of)
        .join(Score, Score.asset_id == Asset.id)
        .filter(Asset.symbol.in_(symbols), Asset.market == "IN")
        .order_by(Score.as_of.desc())
        .all()
    )
    result: dict[str, tuple[float | None, float | None]] = {}
    for symbol, exchange, value, coverage, _as_of in rows:
        key = f"{exchange}:{symbol}"
        if key in result:
            continue  # already have this asset's most recent row (query is ordered desc)
        result[key] = (
            float(value) if value is not None else None,
            float(coverage) if coverage is not None else None,
        )
    return result


def run_ranked_screen(
    db: Session, screen_id: str, *, lookback_days: int | None = None
) -> list[RankedHit]:
    """Layer 1 + Layer 2 (Build_plan.md §K): screens for candidates, then
    re-ranks by Opportunity Score so a hit with weak fundamentals doesn't
    outrank one with stable fundamentals just because it fell further."""
    hits = run_screen(db, screen_id, lookback_days=lookback_days)
    scores = _load_stored_scores(db, {h.asset for h in hits})
    return apply_attention_ranking(hits, scores)


def _load_industries(db: Session, assets: set[AssetRef]) -> dict[str, tuple[str, str]]:
    """symbol -> (industry code, industry name) for whichever hits actually
    need it — same "look up only what the caller has" shape as
    `_load_stored_scores`, and the same reason: this app's Nifty 500
    universe is NSE-only, so keying by plain symbol (not exchange:symbol)
    is enough here, unlike Score which can differ by exchange."""
    if not assets:
        return {}
    symbols = {a.symbol for a in assets}
    rows = (
        db.query(Asset.symbol, Industry.code, Industry.name)
        .join(Company, Company.asset_id == Asset.id)
        .join(Industry, Industry.id == Company.industry_id)
        .filter(Asset.symbol.in_(symbols))
        .all()
    )
    return {symbol: (code, name) for symbol, code, name in rows}


def list_industries(db: Session) -> list[tuple[str, str]]:
    """(code, name) for every industry in the taxonomy, alphabetical by
    name — the options for the homepage's industry filter."""
    rows = db.query(Industry.code, Industry.name).order_by(Industry.name).all()
    return [(code, name) for code, name in rows]


@dataclass(frozen=True, slots=True)
class ScreenOutput:
    ranked: list[RankedHit]
    # symbol -> trailing closes, oldest first. Corporate-action adjusted,
    # because they come from the same bars the screen ran on: an unadjusted
    # split would draw a cliff that never happened.
    sparklines: dict[str, list[float]]
    # symbol -> (industry code, industry name), for whichever hits survived
    # any `industry` filter — lets the API attach industry to each row
    # without a second round-trip.
    industries: dict[str, tuple[str, str]]


# --- Screen result cache -------------------------------------------------
#
# A screen run is by far the most expensive read in this app: it streams
# every active asset's bars over the screen's lookback out of Postgres,
# adjusts them, and evaluates. The result is *shared public market data* —
# identical for every caller — derived from EOD bars that change once a
# day, when the nightly ingestion lands. Recomputing it per request was
# therefore pure waste, and on a metered database it was waste that cost
# real money: /opportunities is public and unauthenticated, so the only
# thing standing between a stranger and the whole month's egress budget
# was the rate limiter, which bounds requests-per-minute and not
# bytes-per-request (SUMMARISER.md §8.9).
#
# Cached UNFILTERED, keyed by (screen_id, sessions) only. The `industry`
# filter is a pure list comprehension over the cached result, so all ~60
# industries share one computation instead of each one being its own cold
# key — which is what a naive (screen, industry) cache would have done,
# and it would have needed ~60x the memory to serve the same answers.
_screen_cache: dict[tuple[str, int], tuple[float, ScreenOutput]] = {}
# One lock per key, not one global lock: two different screens must still
# be able to compute concurrently (the homepage fires four at once), but
# two callers wanting the SAME cold screen must not both load the
# universe. That second case is the one that matters — concurrent
# identical loads are exactly the transient-memory spike that OOM-killed
# this service before (§8.6), so serializing them caps peak memory as
# well as saving the egress.
_screen_locks: dict[tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: tuple[str, int]) -> threading.Lock:
    with _locks_guard:
        lock = _screen_locks.get(key)
        if lock is None:
            lock = _screen_locks[key] = threading.Lock()
        return lock


def _cached_unfiltered(db: Session, screen_id: str, sessions: int) -> ScreenOutput:
    """The full, unfiltered ScreenOutput for one screen, computed at most
    once per TTL across every caller and every industry filter."""
    key = (screen_id, sessions)
    ttl = get_settings().screen_cache_ttl_seconds
    now = time.monotonic()

    entry = _screen_cache.get(key)
    if entry is not None and now - entry[0] < ttl:
        return entry[1]

    with _lock_for(key):
        # Re-check inside the lock: while this thread waited, the thread it
        # was waiting on has almost certainly just stored a fresh result,
        # and recomputing it here would defeat the entire point of the lock.
        entry = _screen_cache.get(key)
        now = time.monotonic()
        if entry is not None and now - entry[0] < ttl:
            return entry[1]
        output = _compute_unfiltered(db, screen_id, sessions)
        _screen_cache[key] = (time.monotonic(), output)
        return output


def clear_screen_cache() -> None:
    """Test hook — the module-level cache would otherwise leak between
    tests, exactly as services/quotes.py's does."""
    with _locks_guard:
        _screen_cache.clear()


def _compute_unfiltered(db: Session, screen_id: str, sessions: int) -> ScreenOutput:
    """The actual work behind `_cached_unfiltered` — one universe load, one
    screen evaluation, sparklines for every hit."""
    hits, universe = _evaluate(db, screen_id, min_bars=sessions)
    scores = _load_stored_scores(db, {h.asset for h in hits})
    ranked = apply_attention_ranking(hits, scores)
    industries = _load_industries(db, {h.asset for h in hits})

    bars_by_symbol = {ref.symbol: bars for ref, bars in universe.items()}
    sparklines = {
        r.hit.asset.symbol: [
            round(bar.close, 2) for bar in bars_by_symbol.get(r.hit.asset.symbol, [])[-sessions:]
        ]
        for r in ranked
    }
    return ScreenOutput(ranked=ranked, sparklines=sparklines, industries=industries)


def run_ranked_screen_with_sparklines(
    db: Session, screen_id: str, *, sessions: int = SPARKLINE_SESSIONS, industry: str | None = None
) -> ScreenOutput:
    """`run_ranked_screen` plus a short closing series per hit.

    Loads `max(screen requirement, sessions)` of history so every screen can
    draw the same length of sparkline — down_5d only needs 6 sessions to
    evaluate, which would otherwise render a 6-point stub next to
    below_dma200's full month.

    Served from the shared screen cache above; `industry` filters that
    cached result rather than driving its own computation. Sparklines are
    now built for every hit rather than only the surviving ones — they
    come off bars the screen already loaded and adjusted, so it is a slice
    per hit and no extra query, and building them once for all industries
    is what lets every industry share one cache entry.
    """
    full = _cached_unfiltered(db, screen_id, sessions)
    if industry is None:
        return full

    ranked = [
        r for r in full.ranked if full.industries.get(r.hit.asset.symbol, ("", ""))[0] == industry
    ]
    return ScreenOutput(
        ranked=ranked,
        sparklines={r.hit.asset.symbol: full.sparklines[r.hit.asset.symbol] for r in ranked},
        industries=full.industries,
    )
