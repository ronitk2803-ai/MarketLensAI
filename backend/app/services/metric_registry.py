"""The one metric vocabulary, shared by the thesis tracker and the
screener — the convergence Build_plan.md §X.1 already assumed ("reuses
the same metric registry the screener/scoring use") but that didn't
actually exist until now.

Each key carries BOTH ways of getting its value:

  `resolve_one`   per-asset, cache-first, may fetch — for the nightly
                  thesis eval, which walks tens of user-authored triggers.
  `resolve_many`  from already-loaded bars — for the screener, which scans
                  ~500 assets in one request and so must never fetch per
                  asset (Build_plan.md §K: "runs entirely against stored
                  data, no live API storms"). Ratio metrics have no bars
                  path; the screener reads them for the whole universe in
                  one query instead (app/services/screener.py).

Both paths delegate to the same pure helpers in
app/engines/opportunity/metrics.py, and a test asserts they return
identical values for every key. Carrying both on one entry is
deliberate: METRIC_KEYS is the thesis API's validation gate, so a key
that existed with only a batch resolver would let a user create a
trigger that silently never fires — the per-asset resolver would return
None forever, with no error anywhere.

Every resolver returns None — never 0, never raising — when its data is
missing, which is what lets evaluate_trigger report "cannot evaluate"
instead of a fabricated result.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import Bar
from app.engines.opportunity import metrics as m
from app.services.adjusted_prices import get_adjusted_bars
from app.services.fundamentals import get_or_fetch_ratios

# How a threshold should be read. Yahoo is not internally consistent —
# `debtToEquity` is a percentage (23.8 means 0.24x) while `revenueGrowth`
# and the margins are fractions (0.15 means 15%) — so a bare number box
# with no unit hint is a trap. The UI labels the threshold input from this.
MetricUnit = Literal["percent", "fraction", "ratio", "multiple", "price", "index"]
MetricGroup = Literal["price", "technical", "valuation", "fundamental"]

# Sessions of history each bars-derived metric needs before it means what
# it says. Two of these are subtler than they look:
#   rsi14  Wilder smoothing is recursive from a seed at index 14 and only
#          settles after ~100 further bars, so declaring 15 would yield a
#          number materially different from the company page's.
#   drawdown_pct  the peak is the window's peak, so the window IS part of
#          the definition — pinned here rather than left to a caller's
#          lookback, which would make one key mean different things.
_RSI_BARS = 120
_DRAWDOWN_BARS = 250


def _lookback_days(required_bars: int) -> int:
    # Imported lazily to keep this module importable from opportunities.py
    # without a cycle.
    from app.services.opportunities import calendar_lookback_for

    return calendar_lookback_for(max(required_bars, 1))


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    label: str
    unit: MetricUnit
    group: MetricGroup
    required_bars: int
    resolve_one: Callable[[Session, Asset], float | None]
    resolve_many: Callable[[list[Bar]], float | None]
    # Set only for ratio metrics: the FinancialMetric row name to read.
    yahoo_field: str | None = field(default=None)


def _ratio(
    key: str, yahoo_field: str, label: str, unit: MetricUnit, group: MetricGroup
) -> MetricSpec:
    def one(db: Session, asset: Asset) -> float | None:
        ratios = {r.metric: float(r.value) for r in get_or_fetch_ratios(db, asset)}
        return ratios.get(yahoo_field)

    return MetricSpec(
        key=key,
        label=label,
        unit=unit,
        group=group,
        required_bars=0,
        resolve_one=one,
        resolve_many=lambda bars: None,
        yahoo_field=yahoo_field,
    )


def _from_bars(
    key: str,
    label: str,
    unit: MetricUnit,
    group: MetricGroup,
    required_bars: int,
    fn: Callable[[list[Bar]], float | None],
) -> MetricSpec:
    """The per-asset path loads its own bars sized by the same
    `required_bars` the screener uses, then runs the identical pure
    function — so the two paths cannot disagree."""

    def one(db: Session, asset: Asset) -> float | None:
        bars, _ = get_adjusted_bars(db, asset, lookback_days=_lookback_days(required_bars))
        return fn(bars)

    return MetricSpec(
        key=key,
        label=label,
        unit=unit,
        group=group,
        required_bars=required_bars,
        resolve_one=one,
        resolve_many=fn,
    )


def _change_spec(period_days: int) -> MetricSpec:
    return _from_bars(
        f"change_{period_days}d_pct",
        f"{period_days}-day price change",
        "percent",
        "price",
        period_days + 1,
        lambda bars, n=period_days: m.change_pct(bars, n),  # type: ignore[misc]
    )


def _dma_gap_spec(period: int) -> MetricSpec:
    return _from_bars(
        f"dma{period}_gap_pct",
        f"Price vs {period}DMA",
        "percent",
        "technical",
        period,
        lambda bars, p=period: m.dma_gap_pct(bars, p),  # type: ignore[misc]
    )


_SPECS: list[MetricSpec] = [
    # --- price ---
    _from_bars("close", "Last close", "price", "price", 1, m.latest_close),
    *[_change_spec(n) for n in (5, 10, 15, 30, 60, 90)],
    # --- technical ---
    *[_dma_gap_spec(p) for p in (20, 50, 100, 200)],
    _from_bars("rsi14", "RSI (14)", "index", "technical", _RSI_BARS, m.rsi14),
    _from_bars("volatility20", "Volatility (20d, annualized)", "fraction", "technical", 21,
               m.volatility20),
    _from_bars("drawdown_pct", "Drawdown from peak", "percent", "technical", _DRAWDOWN_BARS,
               m.drawdown_pct),
    _from_bars("relative_volume", "Relative volume (20d)", "multiple", "technical", 21,
               m.relative_volume20),
    _from_bars("delivery_pct", "Delivery %", "percent", "technical", 1, m.delivery_pct),
    # --- valuation ---
    _ratio("price_to_book", "priceToBook", "Price / book", "ratio", "valuation"),
    _ratio("trailing_pe", "trailingPE", "P/E (trailing)", "ratio", "valuation"),
    _ratio("forward_pe", "forwardPE", "P/E (forward)", "ratio", "valuation"),
    # --- fundamental ---
    _ratio("debt_to_equity", "debtToEquity", "Debt / equity", "percent", "fundamental"),
    _ratio("gross_margins", "grossMargins", "Gross margin", "fraction", "fundamental"),
    _ratio("operating_margins", "operatingMargins", "Operating margin", "fraction", "fundamental"),
    _ratio("profit_margins", "profitMargins", "Net margin", "fraction", "fundamental"),
    _ratio("revenue_growth", "revenueGrowth", "Revenue growth", "fraction", "fundamental"),
    _ratio("earnings_growth", "earningsGrowth", "Earnings growth", "fraction", "fundamental"),
    _ratio("return_on_equity", "returnOnEquity", "Return on equity", "fraction", "fundamental"),
    _ratio("return_on_assets", "returnOnAssets", "Return on assets", "fraction", "fundamental"),
    _ratio("beta", "beta", "Beta", "ratio", "fundamental"),
]

REGISTRY: dict[str, MetricSpec] = {spec.key: spec for spec in _SPECS}

# Every triggerable/screenable metric key, for validating a request at
# creation time (app/api/v1/theses.py, app/api/v1/screener.py) without
# needing a live resolve.
METRIC_KEYS = frozenset(REGISTRY)

RATIO_FIELDS: dict[str, str] = {
    key: spec.yahoo_field for key, spec in REGISTRY.items() if spec.yahoo_field is not None
}


def resolve_metric_value(db: Session, asset: Asset, metric: str) -> float | None:
    spec = REGISTRY.get(metric)
    return spec.resolve_one(db, asset) if spec is not None else None
