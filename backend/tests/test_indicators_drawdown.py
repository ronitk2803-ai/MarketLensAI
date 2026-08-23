import pytest

from app.engines.indicators.drawdown import drawdown_series, max_drawdown


def test_drawdown_series_hand_computed() -> None:
    closes = [100.0, 110.0, 90.0, 95.0, 120.0, 80.0]
    result = drawdown_series(closes)
    assert result == [
        pytest.approx(0.0),
        pytest.approx(0.0),
        pytest.approx((90 - 110) / 110),
        pytest.approx((95 - 110) / 110),
        pytest.approx(0.0),
        pytest.approx((80 - 120) / 120),
    ]


def test_max_drawdown_is_the_worst_point() -> None:
    closes = [100.0, 110.0, 90.0, 95.0, 120.0, 80.0]
    assert max_drawdown(closes) == pytest.approx((80 - 120) / 120)


def test_drawdown_monotonically_rising_series_is_always_zero() -> None:
    assert drawdown_series([1.0, 2.0, 3.0]) == [0.0, 0.0, 0.0]
    assert max_drawdown([1.0, 2.0, 3.0]) == 0.0


def test_max_drawdown_empty_series_is_zero() -> None:
    assert max_drawdown([]) == 0.0
