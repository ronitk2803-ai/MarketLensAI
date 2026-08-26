import datetime as dt
import statistics

import pytest

from app.domain.models import Bar
from app.engines.historical.episodes import detect_episodes
from app.engines.indicators.drawdown import drawdown_series
from app.engines.indicators.volatility import TRADING_DAYS_PER_YEAR, daily_returns


def _bars(closes: list[float]) -> list[Bar]:
    """Consecutive calendar days, so `*_days` and `*_sessions` coincide —
    convenient for hand-computed expectations. `_bars_on` is the variant
    that proves they can diverge."""
    today = dt.date.today()
    n = len(closes)
    return [
        Bar(date=today - dt.timedelta(days=n - 1 - i), open=c, high=c, low=c, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


def _bars_on(dates: list[dt.date], closes: list[float]) -> list[Bar]:
    return [
        Bar(date=d, open=c, high=c, low=c, close=c, volume=1000)
        for d, c in zip(dates, closes, strict=True)
    ]


def test_detect_episodes_finds_one_peak_trough_recovery_cycle() -> None:
    bars = _bars([90, 100, 80, 70, 85, 101])
    (episode,) = detect_episodes(bars)

    assert episode.peak_date == bars[1].date
    assert episode.peak_close == 100
    assert episode.trough_date == bars[3].date
    assert episode.trough_close == 70
    assert episode.recovery_date == bars[5].date
    assert episode.recovery_close == 101
    assert episode.decline_pct == pytest.approx((70 - 100) / 100 * 100)
    assert episode.peak_to_trough_sessions == 2
    assert episode.trough_to_recovery_sessions == 2
    assert episode.recovered is True
    assert episode.left_censored is False


def test_detect_episodes_ignores_declines_shallower_than_the_threshold() -> None:
    assert detect_episodes(_bars([90, 100, 90, 101])) == []
    # ...but the same series is an episode once the threshold moves under it.
    assert len(detect_episodes(_bars([90, 100, 90, 101]), min_decline_pct=5.0)) == 1


def test_a_decline_that_never_recovers_is_returned_as_the_final_open_episode() -> None:
    (episode,) = detect_episodes(_bars([90, 100, 70]))

    assert episode.recovered is False
    assert episode.recovery_date is None
    assert episode.recovery_close is None
    # Never "days so far" — a fall that hasn't recovered has no recovery duration.
    assert episode.trough_to_recovery_days is None
    assert episode.trough_to_recovery_sessions is None


def test_at_most_one_episode_is_open_and_it_is_always_the_last() -> None:
    episodes = detect_episodes(_bars([90, 100, 70, 101, 80, 102, 60]))

    assert len(episodes) == 3
    assert [e.recovered for e in episodes] == [True, True, False]
    assert [e.peak_date for e in episodes] == sorted(e.peak_date for e in episodes)


def test_recovery_requires_a_close_at_or_above_the_peak_not_merely_near_it() -> None:
    (episode,) = detect_episodes(_bars([90, 100, 70, 99.99, 101]))

    # 99.99 is 0.01 short of the peak and does not end the episode.
    assert episode.recovery_date == _bars([90, 100, 70, 99.99, 101])[4].date
    assert episode.trough_to_recovery_sessions == 2


def test_recovering_to_exactly_the_prior_peak_counts_as_recovered() -> None:
    """Pins `>=` rather than `>`: getting back to exactly where it was IS
    getting back to where it was."""
    (episode,) = detect_episodes(_bars([90, 100, 70, 100]))

    assert episode.recovered is True
    assert episode.recovery_close == 100


def test_a_marginal_new_high_between_two_falls_splits_them_into_two_episodes() -> None:
    """Chosen behaviour, not an accident. Requiring a new peak to clear the
    old one by some margin would break what "recovered" means — it would no
    longer be "got back to where it was" — and merging two distinct falls
    into one long episode is the worse and less visible failure. The
    mitigation for the split is that this package computes no aggregate
    across episodes, so nothing averages over the two halves."""
    episodes = detect_episodes(_bars([90, 100, 70, 100.5, 75, 101]))

    assert len(episodes) == 2
    assert episodes[0].decline_pct == pytest.approx(-30.0)
    assert episodes[1].decline_pct == pytest.approx((75 - 100.5) / 100.5 * 100)


def test_left_censored_episode_is_flagged_not_dropped() -> None:
    """The first bar is a peak by construction of the running-peak seed, not
    by observation, so the magnitude is a lower bound. Reporting it with a
    flag is honest; dropping it would hide a real fall, and reporting it
    unflagged would rank a truncated number against measured ones."""
    (episode,) = detect_episodes(_bars([100, 70, 101]))

    assert episode.left_censored is True
    assert episode.decline_pct == pytest.approx(-30.0)


def test_flat_series_produces_no_episodes() -> None:
    """Guards the `<` used to open an episode: with `<=` a flat series would
    open one on bar 1 that could never close."""
    assert detect_episodes(_bars([100.0] * 5)) == []


def test_single_bar_and_empty_series_produce_no_episodes() -> None:
    assert detect_episodes([]) == []
    assert detect_episodes(_bars([100])) == []


def test_first_of_tied_troughs_is_reported() -> None:
    bars = _bars([90, 100, 60, 70, 60, 101])
    (episode,) = detect_episodes(bars)

    assert episode.trough_date == bars[2].date
    assert episode.trough_to_recovery_sessions == 3


def test_non_positive_closes_are_skipped_rather_than_read_as_a_total_loss() -> None:
    (episode,) = detect_episodes(_bars([90, 100, 0, 70, 101]))

    assert episode.decline_pct == pytest.approx(-30.0)
    assert episode.trough_close == 70


def test_decline_pct_matches_drawdown_series_over_the_same_span() -> None:
    """Cross-engine invariant: the episode's magnitude must agree with the
    independent per-bar drawdown computation over the same bars."""
    closes = [90, 100, 80, 70, 85, 101, 88, 60, 102]
    episodes = detect_episodes(_bars(closes))
    series = drawdown_series(closes)

    assert len(episodes) == 2
    for episode in episodes:
        peak_i = closes.index(episode.peak_close)
        trough_i = closes.index(episode.trough_close)
        assert min(series[peak_i : trough_i + 1]) * 100 == pytest.approx(episode.decline_pct)


def test_calendar_days_and_sessions_differ_when_the_market_was_shut() -> None:
    bars = _bars_on(
        [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 5), dt.date(2026, 1, 6)],
        [90, 100, 70, 101],
    )
    (episode,) = detect_episodes(bars)

    # One session apart, three calendar days apart (a weekend in between).
    assert episode.peak_to_trough_sessions == 1
    assert episode.peak_to_trough_days == 3
    assert episode.trough_to_recovery_sessions == 1
    assert episode.trough_to_recovery_days == 1


def test_fall_volatility_is_none_when_the_fall_leg_is_too_short() -> None:
    (episode,) = detect_episodes(_bars([90, 100, 80, 70, 101]))

    assert episode.fall_volatility is None


def test_fall_volatility_matches_stdev_of_daily_returns_annualized() -> None:
    leg = [100, 98, 95, 93, 90, 88, 85, 83, 80, 78, 75, 72]
    (episode,) = detect_episodes(_bars([90, *leg, 101]))

    expected = statistics.stdev(daily_returns(leg)) * TRADING_DAYS_PER_YEAR**0.5
    assert episode.fall_volatility == pytest.approx(expected)


def test_worst_session_is_the_largest_single_day_drop_inside_the_fall_leg() -> None:
    """The tell for a mechanical drop that isn't a real fall: only splits and
    bonuses are price-adjusted (app/engines/adjustment.py), so a demerger or
    rights issue can show up here as one enormous session."""
    bars = _bars([90, 100, 90, 60, 101])
    (episode,) = detect_episodes(bars)

    assert episode.worst_session_pct == pytest.approx((60 - 90) / 90 * 100)
    assert episode.worst_session_date == bars[3].date
