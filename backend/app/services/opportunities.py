"""Runs Layer 1 opportunity screens against stored data only — no live
provider fetch per asset (Build_plan.md §K: "runs entirely against stored
data → fast, no live API storms"). Corporate-action adjustment uses
whatever's already in `corporate_action`; it does not lazily fetch (that
would turn one screen run into N live calls, defeating the point).
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV, Score
from app.domain.models import AssetRef, Bar
from app.engines.adjustment import adjust_bars
from app.engines.opportunity.base import Hit
from app.engines.opportunity.ranking import RankedHit, apply_attention_ranking
from app.engines.opportunity.registry import SCREENS
from app.services.corporate_actions import get_stored_corporate_actions
from app.services.prices import row_to_bar


def _load_universe_bars(db: Session, lookback_days: int) -> dict[AssetRef, list[Bar]]:
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

    universe: dict[AssetRef, list[Bar]] = {}
    for asset_id, price_rows in bars_by_asset.items():
        raw_bars = [row_to_bar(r) for r in price_rows]
        actions = get_stored_corporate_actions(db, asset_id)
        universe[asset_refs[asset_id]] = adjust_bars(raw_bars, actions)
    return universe


def run_screen(db: Session, screen_id: str, *, lookback_days: int = 120) -> list[Hit]:
    screen = SCREENS.get(screen_id)
    if screen is None:
        raise ValueError(f"unknown screen: {screen_id!r}")
    universe = _load_universe_bars(db, lookback_days)
    return screen.evaluate(universe)


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


def run_ranked_screen(db: Session, screen_id: str, *, lookback_days: int = 120) -> list[RankedHit]:
    """Layer 1 + Layer 2 (Build_plan.md §K): screens for candidates, then
    re-ranks by Opportunity Score so a hit with weak fundamentals doesn't
    outrank one with stable fundamentals just because it fell further."""
    hits = run_screen(db, screen_id, lookback_days=lookback_days)
    scores = _load_stored_scores(db, {h.asset for h in hits})
    return apply_attention_ranking(hits, scores)
