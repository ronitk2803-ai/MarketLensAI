import datetime as dt

import pytest

from app.engines.historical.compare import (
    DIMENSIONS_COMPARED,
    DIMENSIONS_UNAVAILABLE,
    SPEC_DIMENSIONS,
    rank_comparables,
)
from app.engines.historical.episodes import Episode


def _episode(decline_pct: float, peak_year: int, *, left_censored: bool = False) -> Episode:
    peak = dt.date(peak_year, 1, 1)
    trough = dt.date(peak_year, 6, 1)
    return Episode(
        peak_date=peak,
        peak_close=100.0,
        trough_date=trough,
        trough_close=100.0 + decline_pct,
        recovery_date=None,
        recovery_close=None,
        decline_pct=decline_pct,
        peak_to_trough_days=(trough - peak).days,
        peak_to_trough_sessions=100,
        trough_to_recovery_days=None,
        trough_to_recovery_sessions=None,
        fall_volatility=None,
        worst_session_pct=-5.0,
        worst_session_date=trough,
        recovered=False,
        left_censored=left_censored,
    )


def test_comparables_are_ordered_by_percentage_point_distance_from_the_current_decline() -> None:
    current = _episode(-35.0, 2026)
    past = [_episode(-70.0, 2021), _episode(-30.0, 2022), _episode(-50.0, 2023)]

    result = rank_comparables(current, past)

    assert [c.episode.decline_pct for c in result.comparable] == [-30.0, -50.0, -70.0]
    assert [c.decline_gap_pp for c in result.comparable] == [
        pytest.approx(5.0),
        pytest.approx(15.0),
        pytest.approx(35.0),
    ]


def test_ties_in_distance_break_towards_the_more_recent_episode() -> None:
    current = _episode(-40.0, 2026)
    # Both are exactly 10 points away — one shallower, one deeper.
    past = [_episode(-30.0, 2021), _episode(-50.0, 2024)]

    result = rank_comparables(current, past)

    assert [c.episode.peak_date.year for c in result.comparable] == [2024, 2021]


def test_left_censored_past_episodes_are_excluded_from_comparables_but_counted() -> None:
    """Their depth is only a lower bound, so ranking one against measured
    depths would compare a truncated number to a real one."""
    current = _episode(-35.0, 2026)
    past = [_episode(-30.0, 2022), _episode(-90.0, 2021, left_censored=True)]

    result = rank_comparables(current, past)

    assert [c.episode.decline_pct for c in result.comparable] == [-30.0]
    assert result.excluded_left_censored == 1
    assert result.past_count == 2


def test_a_left_censored_current_fall_is_still_compared_against() -> None:
    current = _episode(-35.0, 2026, left_censored=True)
    past = [_episode(-30.0, 2022)]

    result = rank_comparables(current, past)

    assert len(result.comparable) == 1
    assert result.comparable[0].decline_gap_pp == pytest.approx(5.0)


def test_without_a_current_fall_past_falls_are_still_returned_most_recent_first() -> None:
    """The panel's job is historical context, so a stock sitting near its
    high must still show what its past falls did — there is simply nothing
    to measure a distance from."""
    past = [_episode(-30.0, 2022), _episode(-50.0, 2024), _episode(-70.0, 2021)]

    result = rank_comparables(None, past)

    assert [c.episode.peak_date.year for c in result.comparable] == [2024, 2022, 2021]
    assert all(c.decline_gap_pp is None for c in result.comparable)
    assert result.past_count == 3


def test_comparables_are_capped_while_past_count_reports_the_full_total() -> None:
    current = _episode(-35.0, 2026)
    past = [_episode(-30.0 - i, 2020 + i) for i in range(9)]

    result = rank_comparables(current, past, limit=5)

    assert len(result.comparable) == 5
    assert result.past_count == 9


def test_no_past_falls_yields_an_empty_comparison() -> None:
    result = rank_comparables(_episode(-35.0, 2026), [])

    assert result.comparable == []
    assert result.past_count == 0
    assert result.excluded_left_censored == 0


def test_spec_dimensions_are_reported_as_unavailable_rather_than_silently_dropped() -> None:
    """Screener.md:465-473 asks that falls be compared on magnitude,
    duration, volatility, news/event type, fundamentals, valuation and
    sector environment. Only the first three are derivable from the data
    this deployment holds. Declaring the other four keeps that a reviewable
    contract, and forces whoever adds one to update this declaration."""
    assert set(SPEC_DIMENSIONS) == set(DIMENSIONS_COMPARED) | set(DIMENSIONS_UNAVAILABLE)
    assert set(DIMENSIONS_COMPARED).isdisjoint(DIMENSIONS_UNAVAILABLE)
    assert set(DIMENSIONS_UNAVAILABLE) == {
        "news_event_type",
        "fundamentals",
        "valuation",
        "sector_environment",
    }
