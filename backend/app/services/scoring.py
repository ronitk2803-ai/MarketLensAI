"""Computes and persists Opportunity Scores (Build_plan.md §L). Gathers
inputs from cache-first services (technicals/fundamentals reuse the same
get_or_fetch pattern the company page already uses — this is a per-asset,
on-demand computation, not a universe scan, so a first-visit live fetch is
acceptable here the way it isn't in opportunities.py).

At most one new `Score` row per asset per day: EOD data doesn't change
intraday, and Build_plan.md §L wants every *meaningful* run snapshotted for
future backtesting, not every page view.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, Score, ScoreComponent, ScoreProfile
from app.engines.indicators import relative_volume as compute_relative_volume
from app.engines.scoring.aggregate import compute_score
from app.engines.scoring.base import ScoreInputs, ScoreResult
from app.engines.scoring.registry import DEFAULT_WEIGHTS
from app.services.adjusted_prices import get_adjusted_bars
from app.services.fundamentals import get_or_fetch_ratios
from app.services.technicals import compute_technicals


def get_active_profile(db: Session, industry_code: str = "default") -> ScoreProfile:
    profile = (
        db.query(ScoreProfile)
        .filter_by(industry_code=industry_code, active=True)
        .order_by(ScoreProfile.version.desc())
        .first()
    )
    if profile is not None:
        return profile
    if industry_code != "default":
        return get_active_profile(db, "default")

    profile = ScoreProfile(industry_code="default", version=1, weights=DEFAULT_WEIGHTS, active=True)
    db.add(profile)
    db.flush()
    return profile


def _gather_inputs(db: Session, asset: Asset) -> ScoreInputs:
    technicals = compute_technicals(db, asset, lookback_days=120)
    ratio_rows = {r.metric: float(r.value) for r in get_or_fetch_ratios(db, asset)}

    # compute_technicals's snapshot doesn't carry volume/delivery% (it's
    # about price indicators) — pull the same underlying adjusted bars
    # (cache-first, so this doesn't double-fetch from a provider) to get
    # relative volume and the latest delivery %.
    bars, _ = get_adjusted_bars(db, asset, lookback_days=120)
    relative_volume = None
    delivery_pct = None
    if bars:
        rv_series = compute_relative_volume([b.volume for b in bars], window=20)
        relative_volume = rv_series[-1]
        delivery_pct = bars[-1].delivery_pct

    return ScoreInputs(
        rsi14=technicals.snapshot.rsi14,
        drawdown_pct=(
            technicals.snapshot.drawdown_pct * 100
            if technicals.snapshot.drawdown_pct is not None
            else None
        ),
        debt_to_equity=ratio_rows.get("debtToEquity"),
        gross_margins=ratio_rows.get("grossMargins"),
        revenue_growth=ratio_rows.get("revenueGrowth"),
        earnings_growth=ratio_rows.get("earningsGrowth"),
        price_to_book=ratio_rows.get("priceToBook"),
        relative_volume=relative_volume,
        delivery_pct=delivery_pct,
    )


def _todays_score(db: Session, asset_id: int, profile_id: int) -> Score | None:
    # "Today" must be measured on the same clock that stamps Score.as_of,
    # which is the database's (server_default=func.now(), UTC). Using
    # dt.date.today() here read the *server's local* date instead, so on any
    # host east of UTC the two disagreed for part of every day: on this
    # IST machine at 00:12 IST the cutoff became 2026-08-24T00:00Z while the
    # row just written carried 2026-08-23T18:42Z, so the lookup missed its
    # own score and every request recomputed — re-fetching fundamentals from
    # Yahoo each time, for the whole 00:00–05:30 IST window.
    today_start = dt.datetime.combine(
        dt.datetime.now(dt.UTC).date(), dt.time.min, tzinfo=dt.UTC
    )
    return (
        db.query(Score)
        .filter(
            Score.asset_id == asset_id,
            Score.profile_id == profile_id,
            Score.as_of >= today_start,
        )
        .order_by(Score.as_of.desc())
        .first()
    )


def get_or_compute_score(db: Session, asset: Asset) -> tuple[Score, list[ScoreComponent]]:
    profile = get_active_profile(db)

    existing = _todays_score(db, asset.id, profile.id)
    if existing is not None:
        components = db.query(ScoreComponent).filter_by(score_id=existing.id).all()
        return existing, components

    inputs = _gather_inputs(db, asset)
    result: ScoreResult = compute_score(inputs, profile.weights)

    confidence = "high" if result.coverage >= 0.6 else "low"
    score = Score(
        asset_id=asset.id,
        profile_id=profile.id,
        value=Decimal(str(round(result.value, 2))) if result.value is not None else None,
        coverage=Decimal(str(round(result.coverage, 3))),
        confidence=confidence,
    )
    db.add(score)
    db.flush()

    components = []
    for c in result.components:
        normalized = (
            Decimal(str(round(c.normalized_value, 2))) if c.normalized_value is not None else None
        )
        contribution = (
            Decimal(str(round(c.contribution, 2))) if c.contribution is not None else None
        )
        component_row = ScoreComponent(
            score_id=score.id,
            component=c.component,
            raw_value=None,
            normalized_value=normalized,
            weight=Decimal(str(c.weight)),
            contribution=contribution,
        )
        db.add(component_row)
        components.append(component_row)
    db.flush()

    return score, components
