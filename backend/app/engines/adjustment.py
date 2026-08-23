"""Corporate-action price adjustment (Build_plan.md §C/§D-007) — pure, no IO.

Applied at read time over data already held: `PriceOHLCV` stores raw
as-reported bars; this computes the adjusted series from those bars plus
`CorporateAction` history, so charts/indicators never see a mechanical
split/bonus jump as if it were a real price move.

Only splits and bonuses get a price/volume adjustment factor here — both
mechanically change the per-share price and share count by a known ratio.
Dividends get an ex-date chart marker (a frontend concern, not implemented
here) but no price adjustment: a dividend's price drop is a market
valuation effect, not a mechanical share-count one. A "total-return
adjusted" view that backs out dividends too would be a distinct feature,
not this one. Rights issues are excluded for the same reason: their price
impact depends on the rights price and subscription ratio together, which
this MVP doesn't model — better to leave rights unadjusted (with an
ex-date marker) than fabricate a formula nobody has verified.
"""

import dataclasses
import datetime as dt
from dataclasses import dataclass

from app.domain.models import Bar, CorporateActionEvent

ADJUSTABLE_ACTION_TYPES = {"split", "bonus"}


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    ex_date: dt.date
    price_factor: float  # multiply pre-ex-date OPEN/HIGH/LOW/CLOSE by this (<=1)
    share_factor: float  # multiply pre-ex-date VOLUME/DELIVERY_QTY by this (>=1)


def compute_adjustment_factors(actions: list[CorporateActionEvent]) -> list[AdjustmentFactor]:
    """One factor per adjustable action, sorted by ex_date ascending.

    `ratio` follows the convention used throughout this codebase (see
    app/db/models.py CorporateAction docstring): ratio=2.0 means a 1:1
    bonus/2:1 split — share count multiplies by 2, price divides by 2.
    """
    factors = []
    for action in actions:
        if action.type not in ADJUSTABLE_ACTION_TYPES:
            continue
        if not action.ratio or action.ratio <= 0:
            continue
        factors.append(
            AdjustmentFactor(
                ex_date=action.ex_date, price_factor=1.0 / action.ratio, share_factor=action.ratio
            )
        )
    return sorted(factors, key=lambda f: f.ex_date)


def _cumulative(factors: list[AdjustmentFactor], bar_date: dt.date, attr: str) -> float:
    """Product of every factor's `attr` whose ex_date is strictly after `bar_date`."""
    result = 1.0
    for f in factors:
        if f.ex_date > bar_date:
            result *= getattr(f, attr)
    return result


def adjust_bars(bars: list[Bar], actions: list[CorporateActionEvent]) -> list[Bar]:
    """New `Bar`s with OHLC and volume/delivery scaled for every split/bonus
    whose ex-date falls after that bar. Bars on/after the most recent
    adjustable action are returned unchanged (factor 1.0)."""
    factors = compute_adjustment_factors(actions)
    if not factors:
        return list(bars)

    adjusted = []
    for bar in bars:
        price_factor = _cumulative(factors, bar.date, "price_factor")
        share_factor = _cumulative(factors, bar.date, "share_factor")
        if price_factor == 1.0 and share_factor == 1.0:
            adjusted.append(bar)
            continue
        adjusted.append(
            dataclasses.replace(
                bar,
                open=bar.open * price_factor,
                high=bar.high * price_factor,
                low=bar.low * price_factor,
                close=bar.close * price_factor,
                volume=round(bar.volume * share_factor),
                delivery_qty=(
                    round(bar.delivery_qty * share_factor) if bar.delivery_qty is not None else None
                ),
            )
        )
    return adjusted
