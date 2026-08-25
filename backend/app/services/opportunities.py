"""Runs Layer 1 opportunity screens against stored data only — no live
provider fetch per asset (Build_plan.md §K: "runs entirely against stored
data → fast, no live API storms"). Corporate-action adjustment uses
whatever's already in `corporate_action`; it does not lazily fetch (that
would turn one screen run into N live calls, defeating the point).
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset, Company, Industry, PriceOHLCV, Score
from app.domain.models import AssetRef, Bar
from app.engines.adjustment import adjust_bars
from app.engines.opportunity.base import Hit
from app.engines.opportunity.ranking import RankedHit, apply_attention_ranking
from app.engines.opportunity.registry import SCREENS
from app.services.corporate_actions import get_stored_corporate_actions_bulk
from app.services.prices import row_to_bar


def load_universe_bars_with_ids(
    db: Session, lookback_days: int
) -> tuple[dict[AssetRef, list[Bar]], dict[AssetRef, int]]:
    """Same as _load_universe_bars, but also hands back each AssetRef's
    row id. AssetRef is a provider-agnostic value object with no id on it
    (app/domain/models.py), so a caller that needs to query another table
    keyed by asset_id — the screener's bulk ratio read — has no way to get
    there from the universe dict alone."""
    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    rows = (
        db.query(PriceOHLCV, Asset)
        .join(Asset, Asset.id == PriceOHLCV.asset_id)
        .filter(
            PriceOHLCV.date >= cutoff,
            Asset.active.is_(True),
            # ETFs slipped into the "EQ" universe (verified live — an ETF
            # unit consolidation showed as a false ~90% crash since our
            # corporate-actions source doesn't track it as a stock split);
            # screens are only meaningful for real listed equities.
            Asset.asset_class == "EQUITY",
        )
        .order_by(Asset.id, PriceOHLCV.date)
        .all()
    )

    bars_by_asset: dict[int, list[PriceOHLCV]] = {}
    asset_refs: dict[int, AssetRef] = {}
    for price_row, asset_row in rows:
        bars_by_asset.setdefault(asset_row.id, []).append(price_row)
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
    actions_by_asset = get_stored_corporate_actions_bulk(db, list(bars_by_asset))

    universe: dict[AssetRef, list[Bar]] = {}
    ids: dict[AssetRef, int] = {}
    for asset_id, price_rows in bars_by_asset.items():
        raw_bars = [row_to_bar(r) for r in price_rows]
        actions = actions_by_asset.get(asset_id, [])
        ref = asset_refs[asset_id]
        universe[ref] = adjust_bars(raw_bars, actions)
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


def run_ranked_screen_with_sparklines(
    db: Session, screen_id: str, *, sessions: int = SPARKLINE_SESSIONS, industry: str | None = None
) -> ScreenOutput:
    """`run_ranked_screen` plus a short closing series per hit.

    Loads `max(screen requirement, sessions)` of history so every screen can
    draw the same length of sparkline — down_5d only needs 6 sessions to
    evaluate, which would otherwise render a 6-point stub next to
    below_dma200's full month.

    `industry`, when given, filters to hits in that industry code *before*
    sparklines are built, so a filtered request doesn't pay to adjust bars
    for rows it's about to throw away.
    """
    hits, universe = _evaluate(db, screen_id, min_bars=sessions)
    scores = _load_stored_scores(db, {h.asset for h in hits})
    ranked = apply_attention_ranking(hits, scores)

    industries = _load_industries(db, {h.asset for h in hits})
    if industry is not None:
        ranked = [r for r in ranked if industries.get(r.hit.asset.symbol, ("", ""))[0] == industry]

    bars_by_symbol = {ref.symbol: bars for ref, bars in universe.items()}
    sparklines = {
        r.hit.asset.symbol: [
            round(bar.close, 2) for bar in bars_by_symbol.get(r.hit.asset.symbol, [])[-sessions:]
        ]
        for r in ranked
    }
    return ScreenOutput(ranked=ranked, sparklines=sparklines, industries=industries)
