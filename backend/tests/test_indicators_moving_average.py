import pytest

from app.engines.indicators.moving_average import ema, sma


def test_sma_basic() -> None:
    values = [1, 2, 3, 4, 5, 6]
    result = sma(values, window=3)
    assert result == [None, None, 2.0, 3.0, 4.0, 5.0]


def test_sma_window_larger_than_series_is_all_none() -> None:
    assert sma([1.0, 2.0], window=5) == [None, None]


def test_sma_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        sma([1.0], window=0)


def test_ema_seeds_with_sma_then_recurses() -> None:
    # Hand-computed: window=2 (k=2/3) on a linear ramp [10,11,12,13,14].
    # seed = SMA([10,11]) = 10.5; then EMA(12)=12*2/3+10.5*1/3=11.5; etc.
    result = ema([10.0, 11.0, 12.0, 13.0, 14.0], window=2)
    assert result[0] is None
    assert result[1] == pytest.approx(10.5)
    assert result[2] == pytest.approx(11.5)
    assert result[3] == pytest.approx(12.5)
    assert result[4] == pytest.approx(13.5)


def test_ema_window_3_linear_ramp() -> None:
    # window=3 (k=0.5): seed = SMA([10,11,12]) = 11; EMA(13)=13*.5+11*.5=12; EMA(14)=13.
    result = ema([10.0, 11.0, 12.0, 13.0, 14.0], window=3)
    assert result == [None, None, pytest.approx(11.0), pytest.approx(12.0), pytest.approx(13.0)]


def test_ema_insufficient_data_returns_all_none() -> None:
    assert ema([1.0, 2.0], window=5) == [None, None]
