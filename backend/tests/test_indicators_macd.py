import pytest

from app.engines.indicators.macd import macd

# Linear ramp closes with small windows (fast=2, slow=3, signal=2) chosen
# specifically so every value is hand-verifiable: EMA of a linear ramp
# converges to a constant offset below price, so fast-slow (macd line) and
# macd-signal (histogram) both settle to clean constants. See derivation in
# the commit message.
CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


def test_macd_matches_hand_computed_linear_ramp() -> None:
    result = macd(CLOSES, fast=2, slow=3, signal=2)

    half = pytest.approx(0.5)
    assert result.macd_line == [None, None, half, half, half]
    assert result.signal_line == [None, None, None, half, half]
    assert result.histogram == [None, None, None, pytest.approx(0.0), pytest.approx(0.0)]


def test_macd_rejects_fast_not_shorter_than_slow() -> None:
    with pytest.raises(ValueError):
        macd(CLOSES, fast=26, slow=12, signal=9)


def test_macd_insufficient_data_is_all_none() -> None:
    result = macd([1.0, 2.0], fast=12, slow=26, signal=9)
    assert result.macd_line == [None, None]
    assert result.signal_line == [None, None]
    assert result.histogram == [None, None]
