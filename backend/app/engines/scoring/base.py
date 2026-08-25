"""Scoring engine (Build_plan.md §L) — pure, no IO.

The score represents "research attractiveness / opportunity characteristics"
— never a return prediction (product_principles.md, enforced in copy). It's
a rule-based v1: weights are configuration (never hardcoded — see
registry.py's DEFAULT_WEIGHTS is only a *seed* for the DB-stored profile,
not what's used at runtime), and none of it has been backtested or
validated against real outcomes. That calibration work is explicitly P2
(Build_plan.md §L: "Future versions should support historical validation,
backtesting, optimization").

Missing-data-graceful (§L): each component returns `None` when its inputs
are unavailable rather than a guessed value; the aggregator renormalizes
over only the components that had data and reports the resulting coverage.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    """Everything a component might read, gathered once per scoring run
    from data already stored (technicals + fundamentals) — components
    never fetch anything themselves."""

    rsi14: float | None = None
    drawdown_pct: float | None = None
    # Yahoo's `debtToEquity` is a PERCENTAGE, not a ratio (live Nifty 500
    # median ~23.8, i.e. 0.24x). Kept in the source's own unit here because
    # that's what the UI displays and what thesis_metrics.py exposes under
    # the same name; components.fundamental_quality does the conversion.
    debt_to_equity: float | None = None
    gross_margins: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    price_to_book: float | None = None
    trailing_pe: float | None = None
    relative_volume: float | None = None
    delivery_pct: float | None = None


@dataclass(frozen=True, slots=True)
class ComponentResult:
    component: str
    raw_value: float | None
    normalized_value: float | None  # 0-100, higher = more attractive; None if unavailable
    weight: float
    contribution: float | None  # this component's actual share of the final score


@dataclass(frozen=True, slots=True)
class ScoreResult:
    value: float | None  # 0-100, or None if literally no component had data
    coverage: float  # fraction of total weight-mass that had data, 0-1
    components: list[ComponentResult]


def clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
