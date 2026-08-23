import statistics

import pytest

from app.engines.indicators.volatility import (
    TRADING_DAYS_PER_YEAR,
    daily_returns,
    historical_volatility,
)


def test_daily_returns_basic() -> None:
    result = daily_returns([100.0, 110.0, 99.0])
    assert result == [pytest.approx(0.10), pytest.approx(-0.10)]


def test_historical_volatility_zero_for_constant_prices() -> None:
    closes = [100.0] * 10
    result = historical_volatility(closes, window=3)
    assert result[3] == pytest.approx(0.0)
    assert result[-1] == pytest.approx(0.0)


def test_historical_volatility_matches_reference_stdev_calculation() -> None:
    closes = [100.0, 102.0, 98.0, 101.0, 100.0, 103.0]
    result = historical_volatility(closes, window=3, annualize=False)

    returns = daily_returns(closes)
    # Independently recompute via the stdlib, not the module under test.
    expected_at_5 = statistics.stdev(returns[2:5])
    assert result[5] == pytest.approx(expected_at_5)
    assert result[0] is None
    assert result[1] is None
    assert result[2] is None


def test_historical_volatility_annualizes_by_sqrt_trading_days() -> None:
    closes = [100.0, 102.0, 98.0, 101.0, 100.0, 103.0]
    raw = historical_volatility(closes, window=3, annualize=False)
    annualized = historical_volatility(closes, window=3, annualize=True)
    assert annualized[5] == pytest.approx(raw[5] * TRADING_DAYS_PER_YEAR**0.5)


def test_historical_volatility_rejects_window_below_2() -> None:
    with pytest.raises(ValueError):
        historical_volatility([1.0, 2.0], window=1)
