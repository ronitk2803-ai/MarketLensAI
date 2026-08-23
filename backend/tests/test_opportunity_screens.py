import datetime as dt

import pytest

from app.domain.models import AssetRef, Bar
from app.engines.opportunity.screens import BelowDMA, DownOverPeriod, UnusualVolume

DOWN_STOCK = AssetRef(symbol="DOWNCO", exchange="NSE")
FLAT_STOCK = AssetRef(symbol="FLATCO", exchange="NSE")
UP_STOCK = AssetRef(symbol="UPCO", exchange="NSE")


def _bars(closes: list[float], volumes: list[int] | None = None) -> list[Bar]:
    today = dt.date.today()
    n = len(closes)
    volumes = volumes or [1000] * n
    return [
        Bar(date=today - dt.timedelta(days=n - 1 - i), open=c, high=c, low=c, close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
    ]


def test_down_over_period_hits_only_declines_past_threshold() -> None:
    universe = {
        DOWN_STOCK: _bars([100.0] * 20 + [80.0]),  # -20% over 20d
        FLAT_STOCK: _bars([100.0] * 21),  # flat
        UP_STOCK: _bars([100.0] * 20 + [120.0]),  # +20%
    }
    screen = DownOverPeriod("down_20d", period_days=20, min_decline_pct=10.0)

    hits = screen.evaluate(universe)

    assert [h.asset for h in hits] == [DOWN_STOCK]
    assert hits[0].metrics["change_pct"] == -20.0


def test_down_over_period_skips_assets_with_insufficient_history() -> None:
    universe = {DOWN_STOCK: _bars([100.0, 90.0])}  # only 2 bars, need > 20
    screen = DownOverPeriod("down_20d", period_days=20, min_decline_pct=10.0)
    assert screen.evaluate(universe) == []


def test_down_over_period_sorts_worst_decline_first() -> None:
    universe = {
        DOWN_STOCK: _bars([100.0] * 10 + [70.0]),  # -30%
        FLAT_STOCK: _bars([100.0] * 10 + [85.0]),  # -15%
    }
    screen = DownOverPeriod("down_10d", period_days=10, min_decline_pct=10.0)
    hits = screen.evaluate(universe)
    assert [h.asset for h in hits] == [DOWN_STOCK, FLAT_STOCK]


def test_below_dma_hits_only_when_close_under_average() -> None:
    # 5-day DMA is the rolling mean of the *last* 5 closes (includes the
    # latest bar itself): [100,100,100,100,90] -> 98.0. close=90 < 98.0.
    universe = {
        DOWN_STOCK: _bars([100.0, 100.0, 100.0, 100.0, 100.0, 90.0]),
        UP_STOCK: _bars([100.0, 100.0, 100.0, 100.0, 100.0, 110.0]),
    }
    screen = BelowDMA("below_dma5", dma_period=5)

    hits = screen.evaluate(universe)

    assert [h.asset for h in hits] == [DOWN_STOCK]
    assert hits[0].metrics["dma"] == 98.0
    assert hits[0].metrics["pct_below"] == pytest.approx((90.0 - 98.0) / 98.0 * 100)


def test_below_dma_skips_assets_without_enough_history_for_the_window() -> None:
    universe = {DOWN_STOCK: _bars([100.0, 90.0])}  # need 5 bars for a 5-day DMA
    screen = BelowDMA("below_dma5", dma_period=5)
    assert screen.evaluate(universe) == []


def test_unusual_volume_hits_only_above_multiplier() -> None:
    # 20-day trailing average volume = 1000; day 21 volume = 3000 -> 3x.
    universe = {
        DOWN_STOCK: _bars([100.0] * 21, volumes=[1000] * 20 + [3000]),
        FLAT_STOCK: _bars([100.0] * 21, volumes=[1000] * 20 + [1200]),
    }
    screen = UnusualVolume("unusual_volume", window=20, min_multiplier=2.0)

    hits = screen.evaluate(universe)

    assert [h.asset for h in hits] == [DOWN_STOCK]
    assert hits[0].metrics["relative_volume"] == 3.0


def test_unusual_volume_sorts_highest_multiplier_first() -> None:
    universe = {
        DOWN_STOCK: _bars([100.0] * 21, volumes=[1000] * 20 + [2500]),
        UP_STOCK: _bars([100.0] * 21, volumes=[1000] * 20 + [5000]),
    }
    screen = UnusualVolume("unusual_volume", window=20, min_multiplier=2.0)
    hits = screen.evaluate(universe)
    assert [h.asset for h in hits] == [UP_STOCK, DOWN_STOCK]


def test_screens_handle_empty_universe() -> None:
    assert DownOverPeriod("x", period_days=5, min_decline_pct=1.0).evaluate({}) == []
    assert BelowDMA("y", dma_period=5).evaluate({}) == []
    assert UnusualVolume("z").evaluate({}) == []


def test_every_registered_screen_declares_enough_history_to_ever_match() -> None:
    """Guards against a screen being listed in the UI but mathematically dead.

    below_dma100 and below_dma200 shipped this way: run_screen defaulted to a
    flat 120 *calendar* days (~82 trading sessions) while sma() needs a full
    window before it returns anything, so both screens returned zero hits
    forever regardless of the market. Verified live against a fully
    backfilled universe at the time: below_dma50 -> 1137 hits,
    below_dma100 -> 0, below_dma200 -> 0.
    """
    from app.engines.opportunity.registry import SCREENS
    from app.services.opportunities import calendar_lookback_for

    # NSE trades ~246 sessions a year; a calendar window yields ~0.67x that.
    trading_days_per_calendar_day = 246 / 365

    for screen_id, screen in SCREENS.items():
        lookback = calendar_lookback_for(screen.required_bars)
        sessions_available = lookback * trading_days_per_calendar_day
        assert sessions_available >= screen.required_bars, (
            f"{screen_id} needs {screen.required_bars} sessions but its "
            f"{lookback}-calendar-day window only yields ~{sessions_available:.0f}"
        )
