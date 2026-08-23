import datetime as dt

from app.domain.models import Bar, CorporateActionEvent
from app.engines.adjustment import adjust_bars, compute_adjustment_factors

# Real raw (unadjusted) NSE bhavcopy bars for RELIANCE around its 2024-10-28
# bonus issue, captured live 2026-08-23: 1:1 bonus (Yahoo reports it as a
# "2:1 split", ratio=2.0), ex-date 2024-10-28. Raw close roughly halved
# 2655.70 -> 1334.35 on the ex-date itself (a real 1-day market move sits
# on top of the exact 2x, which is expected and correct).
RAW_BARS = [
    Bar(
        date=dt.date(2024, 10, 25), open=2687.00, high=2688.70, low=2644.00, close=2655.70,
        volume=9_298_748,
    ),
    Bar(
        date=dt.date(2024, 10, 28), open=1337.00, high=1353.00, low=1322.10, close=1334.35,
        volume=10_824_350,
    ),
    Bar(
        date=dt.date(2024, 10, 29), open=1328.10, high=1343.20, low=1320.30, close=1340.00,
        volume=12_008_361,
    ),
]
BONUS = CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0)


def test_compute_adjustment_factors_ignores_dividends_and_zero_ratio() -> None:
    events = [
        BONUS,
        CorporateActionEvent(type="dividend", ex_date=dt.date(2024, 8, 1), amount=8.0),
        CorporateActionEvent(type="split", ex_date=dt.date(2020, 1, 1), ratio=None),
    ]
    factors = compute_adjustment_factors(events)
    assert len(factors) == 1
    assert factors[0].ex_date == dt.date(2024, 10, 28)
    assert factors[0].price_factor == 0.5
    assert factors[0].share_factor == 2.0


def test_adjust_bars_scales_pre_ex_date_bars_only() -> None:
    adjusted = adjust_bars(RAW_BARS, [BONUS])

    before = adjusted[0]
    on_ex_date = adjusted[1]
    after = adjusted[2]

    # Pre-ex-date bar: price halved, volume doubled.
    assert before.close == 2655.70 * 0.5
    assert before.open == 2687.00 * 0.5
    assert before.volume == 9_298_748 * 2

    # On and after the ex-date, the raw bars already reflect the new share
    # basis — must be untouched.
    assert on_ex_date == RAW_BARS[1]
    assert after == RAW_BARS[2]


def test_adjust_bars_roughly_aligns_pre_and_post_ex_date_price_level() -> None:
    """Sanity check against reality: after adjustment, the raw ~2x mechanical
    jump should collapse to an ordinary single-day price move (a few percent),
    not remain a ~100% jump."""
    adjusted = adjust_bars(RAW_BARS, [BONUS])
    pct_change = abs(adjusted[1].close - adjusted[0].close) / adjusted[0].close
    assert pct_change < 0.05


def test_adjust_bars_is_noop_with_no_adjustable_actions() -> None:
    assert adjust_bars(RAW_BARS, []) == RAW_BARS
    dividend_only = [CorporateActionEvent(type="dividend", ex_date=dt.date(2024, 8, 1), amount=8.0)]
    assert adjust_bars(RAW_BARS, dividend_only) == RAW_BARS


def test_adjust_bars_cascades_multiple_actions() -> None:
    """A bar before two separate bonus issues must be scaled by BOTH factors."""
    bars = [Bar(date=dt.date(2016, 1, 1), open=100, high=100, low=100, close=100, volume=1000)]
    actions = [
        CorporateActionEvent(type="split", ex_date=dt.date(2017, 9, 7), ratio=2.0),
        CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0),
    ]
    adjusted = adjust_bars(bars, actions)
    assert adjusted[0].close == 25.0  # 100 / 2 / 2
    assert adjusted[0].volume == 4000  # 1000 * 2 * 2


def test_adjust_bars_handles_missing_delivery_qty() -> None:
    bars = [Bar(date=dt.date(2024, 10, 25), open=1, high=1, low=1, close=1, volume=100)]
    adjusted = adjust_bars(bars, [BONUS])
    assert adjusted[0].delivery_qty is None
