import pytest

from app.engines.indicators.relative import relative_strength, relative_volume


def test_relative_strength_outperformance() -> None:
    # Asset up 20% total, benchmark up 10% total -> asset index 120 vs
    # benchmark index 110 -> relative strength = 120/110*100 = 109.09.
    asset = [100.0, 110.0, 120.0]
    benchmark = [1000.0, 1050.0, 1100.0]
    result = relative_strength(asset, benchmark)
    assert result[0] == pytest.approx(100.0)
    assert result[-1] == pytest.approx(120 / 110 * 100)


def test_relative_strength_underperformance() -> None:
    asset = [100.0, 95.0, 90.0]
    benchmark = [1000.0, 1000.0, 1000.0]
    result = relative_strength(asset, benchmark)
    assert result[-1] == pytest.approx(90.0)  # asset down 10%, benchmark flat


def test_relative_strength_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        relative_strength([1.0, 2.0], [1.0])


def test_relative_strength_empty_series() -> None:
    assert relative_strength([], []) == []


def test_relative_volume_hand_computed() -> None:
    # window=3 prior days [10,20,30] avg=20; today=40 -> 40/20=2.0.
    volumes = [10, 20, 30, 40]
    result = relative_volume(volumes, window=3)
    assert result == [None, None, None, pytest.approx(2.0)]


def test_relative_volume_below_average() -> None:
    volumes = [100, 100, 100, 50]
    result = relative_volume(volumes, window=3)
    assert result[-1] == pytest.approx(0.5)


def test_relative_volume_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        relative_volume([1, 2], window=0)
