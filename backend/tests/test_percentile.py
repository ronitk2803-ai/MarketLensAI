import pytest

from app.engines.scoring.percentile import percentile_rank


def test_percentile_rank_of_the_minimum_is_low() -> None:
    assert percentile_rank(1.0, [1.0, 2.0, 3.0, 4.0]) == pytest.approx(25.0)


def test_percentile_rank_of_the_maximum_is_full() -> None:
    assert percentile_rank(4.0, [1.0, 2.0, 3.0, 4.0]) == pytest.approx(100.0)


def test_percentile_rank_of_the_median() -> None:
    assert percentile_rank(2.0, [1.0, 2.0, 3.0]) == pytest.approx(66.666, rel=1e-3)


def test_percentile_rank_ties_count_as_at_or_below() -> None:
    # Three values <= 2.0 out of four peers.
    assert percentile_rank(2.0, [1.0, 2.0, 2.0, 3.0]) == pytest.approx(75.0)


def test_percentile_rank_single_peer() -> None:
    assert percentile_rank(5.0, [5.0]) == pytest.approx(100.0)


def test_percentile_rank_value_below_every_peer() -> None:
    assert percentile_rank(0.0, [10.0, 20.0, 30.0]) == pytest.approx(0.0)


def test_percentile_rank_value_above_every_peer() -> None:
    assert percentile_rank(100.0, [10.0, 20.0, 30.0]) == pytest.approx(100.0)


def test_percentile_rank_rejects_an_empty_peer_list() -> None:
    with pytest.raises(ValueError):
        percentile_rank(1.0, [])
