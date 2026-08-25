"""The combinable screener (Build_plan.md §K / P2 step 22): runs a
user-authored AND/OR condition tree over the whole universe.

The one rule this has to honour is §K:341 — "runs entirely against
stored data, no live API storms". The registry's per-asset resolver
can't be used here: it re-reads and recomputes per call and may fetch
from a provider, which across ~500 assets would be hundreds of live
calls inside one request. So every metric is resolved as a *column*
instead: ratios in a single bulk read of the FinancialMetric
latest-value cache, and everything else computed from the bars the
universe load already produced. No per-asset query, no network.
"""

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import FinancialMetric
from app.domain.models import AssetRef, Bar
from app.engines.opportunity.base import Hit
from app.engines.opportunity.conditions import Node, collect_metrics, matches
from app.engines.opportunity.ranking import RankedHit, apply_attention_ranking
from app.services.metric_registry import RATIO_FIELDS, REGISTRY
from app.services.opportunities import (
    SPARKLINE_SESSIONS,
    _load_industries,
    _load_stored_scores,
    calendar_lookback_for,
    load_universe_bars_with_ids,
)

# Marks hits that came from a condition tree rather than a registered
# screen. Hit.screen_id is a required scalar and a combined result has no
# natural single screen — a sentinel keeps the shape (and the frontend
# type) unchanged. A test asserts this never collides with a real screen.
CUSTOM_SCREEN_ID = "custom"


def _finite(value: float | None) -> float | None:
    """FastAPI's JSON encoder emits bare NaN/Infinity, which the browser's
    JSON.parse rejects outright. Every indicator guards its own divisors,
    so this should never fire — but a single non-finite value would break
    the whole response rather than one cell."""
    if value is None or not math.isfinite(value):
        return None
    return value


def resolve_metric_columns(
    db: Session,
    metrics: set[str],
    universe: dict[AssetRef, list[Bar]],
    asset_ids: dict[AssetRef, int],
) -> dict[str, dict[AssetRef, float | None]]:
    """metric -> {asset -> value}, for the whole universe at once."""
    columns: dict[str, dict[AssetRef, float | None]] = {}

    wanted_ratios = {key: RATIO_FIELDS[key] for key in metrics if key in RATIO_FIELDS}
    if wanted_ratios:
        # One query for every ratio of every asset. FinancialMetric is a
        # latest-value cache keyed (asset_id, metric), so there's no
        # history to window and nothing to deduplicate.
        ids_to_ref = {asset_id: ref for ref, asset_id in asset_ids.items()}
        rows = (
            db.query(FinancialMetric.asset_id, FinancialMetric.metric, FinancialMetric.value)
            .filter(
                FinancialMetric.asset_id.in_(list(ids_to_ref)),
                FinancialMetric.metric.in_(set(wanted_ratios.values())),
            )
            .all()
        )
        by_field: dict[str, dict[AssetRef, float | None]] = {
            field: {} for field in wanted_ratios.values()
        }
        for asset_id, field, value in rows:
            ref = ids_to_ref.get(asset_id)
            if ref is not None:
                by_field[field][ref] = _finite(float(value))
        for key, field in wanted_ratios.items():
            columns[key] = by_field[field]

    for key in metrics:
        if key in columns:
            continue
        spec = REGISTRY.get(key)
        if spec is None:
            continue
        columns[key] = {ref: _finite(spec.resolve_many(bars)) for ref, bars in universe.items()}

    return columns


def required_lookback_days(metrics: set[str], *, min_bars: int = 0) -> int:
    """Sized from only the metrics this tree actually references, so a
    cheap tree stays cheap — `close lt 100` reads about a month, not the
    ~300 sessions a dma200_gap_pct condition forces. Taking the max over
    every known metric instead would quietly destroy that."""
    needed = [REGISTRY[key].required_bars for key in metrics if key in REGISTRY]
    return calendar_lookback_for(max([*needed, min_bars, 1]))


@dataclass(frozen=True, slots=True)
class MetricCoverage:
    metric: str
    available: int
    total: int


@dataclass(frozen=True, slots=True)
class ScreenerOutput:
    ranked: list[RankedHit]
    sparklines: dict[str, list[float]]
    industries: dict[str, tuple[str, str]]
    # Per-metric evaluable counts. Excluding an asset because a metric is
    # missing is correct, but leaving that invisible would make "no data"
    # and "no match" indistinguishable — the one thing this codebase
    # consistently refuses to do (evaluate_trigger's None, MIN_SECTOR_SAMPLE,
    # every provenance envelope). The API reports these so an empty result
    # is explicable rather than mysterious.
    coverage: list[MetricCoverage]
    universe_size: int


def run_condition_screen(
    db: Session,
    tree: Node,
    *,
    industry: str | None = None,
    sessions: int = SPARKLINE_SESSIONS,
) -> ScreenerOutput:
    metrics = collect_metrics(tree)
    universe, asset_ids = load_universe_bars_with_ids(
        db, required_lookback_days(metrics, min_bars=sessions)
    )
    columns = resolve_metric_columns(db, metrics, universe, asset_ids)

    hits: list[Hit] = []
    for ref in universe:
        values = {metric: columns.get(metric, {}).get(ref) for metric in metrics}
        if not matches(tree, values):
            continue
        hits.append(
            Hit(
                asset=ref,
                screen_id=CUSTOM_SCREEN_ID,
                # Every metric the tree filtered on, so the results table
                # shows exactly the numbers the user screened by. None
                # values are omitted rather than widening Hit.metrics —
                # the frontend already renders a missing key as "—".
                metrics={k: v for k, v in values.items() if v is not None},
            )
        )

    # Filtered BEFORE ranking, unlike the preset path, so ranks come out
    # contiguous 1..N. Ranking first and filtering after (what
    # run_ranked_screen_with_sparklines does) leaves a filtered list
    # reading 7, 19, 44.
    industries = _load_industries(db, {h.asset for h in hits})
    if industry is not None:
        hits = [h for h in hits if industries.get(h.asset.symbol, ("", ""))[0] == industry]

    scores = _load_stored_scores(db, {h.asset for h in hits})
    ranked = apply_attention_ranking(hits, scores)

    bars_by_symbol = {ref.symbol: bars for ref, bars in universe.items()}
    sparklines = {
        r.hit.asset.symbol: [
            round(bar.close, 2) for bar in bars_by_symbol.get(r.hit.asset.symbol, [])[-sessions:]
        ]
        for r in ranked
    }
    coverage = [
        MetricCoverage(
            metric=metric,
            available=sum(1 for v in columns.get(metric, {}).values() if v is not None),
            total=len(universe),
        )
        for metric in sorted(metrics)
    ]
    return ScreenerOutput(
        ranked=ranked,
        sparklines=sparklines,
        industries=industries,
        coverage=coverage,
        universe_size=len(universe),
    )
