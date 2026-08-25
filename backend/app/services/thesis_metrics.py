"""The metric registry Build_plan.md §X.1 refers to ("reuses the same
metric registry the screener/scoring use") doesn't actually exist yet as a
literal shared module — app/engines/opportunity/screens.py's screens each
compute what they need directly, with no shared name -> resolver mapping.
This is the first one: a fixed set of metric keys a thesis trigger can
reference, each backed by a resolver over data this app already fetches
(app/services/fundamentals.py's ratios, app/services/technicals.py's
snapshot).

Every resolver returns None — never 0, never raises — when its underlying
data is missing, which is what lets app/engines/thesis/base.py's
evaluate_trigger report "cannot evaluate" instead of a fabricated result
(Build_plan.md §X.1's edge case).
"""

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.services.fundamentals import get_or_fetch_ratios
from app.services.technicals import TechnicalSnapshot, compute_technicals

_RATIO_METRICS = {
    "debt_to_equity": "debtToEquity",
    "price_to_book": "priceToBook",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "gross_margins": "grossMargins",
    "operating_margins": "operatingMargins",
    "profit_margins": "profitMargins",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "return_on_equity": "returnOnEquity",
    "return_on_assets": "returnOnAssets",
    "beta": "beta",
}

_TECHNICAL_SNAPSHOT_METRICS = {
    "rsi14": "rsi14",
    "drawdown_pct": "drawdown_pct",
    "volatility20": "volatility20",
    "close": "close",
}

_DMA_GAP_PERIODS = {
    "dma20_gap_pct": "dma20",
    "dma50_gap_pct": "dma50",
    "dma100_gap_pct": "dma100",
    "dma200_gap_pct": "dma200",
}

# Every triggerable metric key, for validating a trigger at creation time
# (app/api/v1/theses.py) without needing a live resolve.
METRIC_KEYS = frozenset(
    [*_RATIO_METRICS, *_TECHNICAL_SNAPSHOT_METRICS, *_DMA_GAP_PERIODS]
)


def _dma_gap_pct(snapshot: TechnicalSnapshot, dma_attr: str) -> float | None:
    """(close - dmaN) / dmaN * 100 — the exact formula
    app/engines/opportunity/screens.py's BelowDMA screen uses for
    pct_below, reused here so "price < 200DMA" (Build_plan.md §X.1's own
    example trigger) becomes one scalar comparison
    (metric=dma200_gap_pct, operator=lt, threshold=0) instead of a
    two-value one — consistent with every other trigger shape."""
    dma_value = getattr(snapshot, dma_attr)
    if snapshot.close is None or dma_value is None or dma_value == 0:
        return None
    return (snapshot.close - dma_value) / dma_value * 100


def resolve_metric_value(db: Session, asset: Asset, metric: str) -> float | None:
    if metric in _RATIO_METRICS:
        yahoo_field = _RATIO_METRICS[metric]
        ratios = {r.metric: float(r.value) for r in get_or_fetch_ratios(db, asset)}
        return ratios.get(yahoo_field)

    if metric in _TECHNICAL_SNAPSHOT_METRICS:
        # Deliberately NOT the lookback_days=120 app/services/scoring.py's
        # gather_score_inputs uses — that's only ~85 trading sessions,
        # which would leave dma200 (and this whole metric family)
        # permanently None. compute_technicals's own default (450) is
        # enough for every DMA period this registry exposes.
        snapshot = compute_technicals(db, asset).snapshot
        return getattr(snapshot, _TECHNICAL_SNAPSHOT_METRICS[metric])

    if metric in _DMA_GAP_PERIODS:
        snapshot = compute_technicals(db, asset).snapshot
        return _dma_gap_pct(snapshot, _DMA_GAP_PERIODS[metric])

    return None
