import pytest

from app.engines.indicators.rsi import rsi

# Hand-computed with period=3 (Wilder's smoothing), see the derivation in
# the PR description / commit message. closes[0..2] have no RSI (need 3
# deltas); closes[3..7] are the first five valid values.
CLOSES = [44, 44.5, 43.5, 45, 46, 45.5, 46.5, 47]
EXPECTED = [None, None, None, 66.667, 77.778, 62.222, 76.387, 81.574]


def test_rsi_matches_hand_computed_wilder_values() -> None:
    result = rsi(CLOSES, period=3)
    assert len(result) == len(CLOSES)
    for actual, expected in zip(result, EXPECTED, strict=True):
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(expected, abs=1e-2)


def test_rsi_all_gains_is_100() -> None:
    result = rsi([10.0, 11.0, 12.0, 13.0, 14.0], period=3)
    assert result[3] == pytest.approx(100.0)
    assert result[4] == pytest.approx(100.0)


def test_rsi_all_losses_is_0() -> None:
    result = rsi([14.0, 13.0, 12.0, 11.0, 10.0], period=3)
    assert result[3] == pytest.approx(0.0)
    assert result[4] == pytest.approx(0.0)


def test_rsi_insufficient_data_is_all_none() -> None:
    assert rsi([1.0, 2.0, 3.0], period=14) == [None, None, None]


def test_rsi_rejects_invalid_period() -> None:
    with pytest.raises(ValueError):
        rsi([1.0], period=0)
