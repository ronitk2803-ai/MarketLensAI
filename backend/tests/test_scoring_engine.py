import pytest

from app.engines.scoring.aggregate import compute_score
from app.engines.scoring.base import ScoreInputs
from app.engines.scoring.components import (
    fundamental_quality,
    growth,
    participation,
    technical_setup,
    valuation,
)


def test_valuation_scores_low_pb_highly() -> None:
    assert valuation(ScoreInputs(price_to_book=1.0)) == pytest.approx(100.0)
    assert valuation(ScoreInputs(price_to_book=6.0)) == pytest.approx(0.0)
    assert valuation(ScoreInputs(price_to_book=3.5)) == pytest.approx(50.0)


def test_valuation_none_when_missing() -> None:
    assert valuation(ScoreInputs()) is None


def test_valuation_clips_beyond_bounds() -> None:
    assert valuation(ScoreInputs(price_to_book=0.0)) == pytest.approx(100.0)
    assert valuation(ScoreInputs(price_to_book=20.0)) == pytest.approx(0.0)


def test_fundamental_quality_blends_debt_and_margin() -> None:
    debt_only = fundamental_quality(ScoreInputs(debt_to_equity=0.5))
    assert debt_only == pytest.approx(100.0)
    margin_only = fundamental_quality(ScoreInputs(gross_margins=0.40))
    assert margin_only == pytest.approx(100.0)
    both = fundamental_quality(ScoreInputs(debt_to_equity=0.5, gross_margins=0.40))
    assert both == pytest.approx(100.0)
    both_mid = fundamental_quality(ScoreInputs(debt_to_equity=3.0, gross_margins=0.0))
    assert both_mid == pytest.approx(0.0)


def test_fundamental_quality_none_when_both_missing() -> None:
    assert fundamental_quality(ScoreInputs()) is None


def test_growth_neutral_at_zero() -> None:
    assert growth(ScoreInputs(revenue_growth=0.0, earnings_growth=0.0)) == pytest.approx(50.0)


def test_growth_saturates_at_extremes() -> None:
    assert growth(ScoreInputs(revenue_growth=1.0, earnings_growth=1.0)) == pytest.approx(100.0)
    assert growth(ScoreInputs(revenue_growth=-1.0, earnings_growth=-1.0)) == pytest.approx(0.0)


def test_technical_setup_rewards_larger_drawdown_and_lower_rsi() -> None:
    deep_decline = technical_setup(ScoreInputs(drawdown_pct=-40.0, rsi14=20.0))
    assert deep_decline == pytest.approx(100.0)
    no_decline = technical_setup(ScoreInputs(drawdown_pct=0.0, rsi14=70.0))
    assert no_decline == pytest.approx(0.0)


def test_participation_blends_relative_volume_and_delivery() -> None:
    result = participation(ScoreInputs(relative_volume=3.0, delivery_pct=100.0))
    assert result == pytest.approx(100.0)
    result_none = participation(ScoreInputs())
    assert result_none is None


WEIGHTS = {
    "valuation": 0.25,
    "fundamental_quality": 0.25,
    "growth": 0.20,
    "technical_setup": 0.15,
    "participation": 0.15,
}


def test_compute_score_full_coverage() -> None:
    inputs = ScoreInputs(
        price_to_book=1.0,  # valuation=100
        debt_to_equity=0.5,
        gross_margins=0.40,  # fundamental_quality=100
        revenue_growth=1.0,
        earnings_growth=1.0,  # growth=100
        drawdown_pct=-40.0,
        rsi14=20.0,  # technical_setup=100
        relative_volume=3.0,
        delivery_pct=100.0,  # participation=100
    )
    result = compute_score(inputs, WEIGHTS)
    assert result.value == pytest.approx(100.0)
    assert result.coverage == pytest.approx(1.0)
    assert len(result.components) == 5


def test_compute_score_renormalizes_over_missing_components() -> None:
    # Only valuation (weight 0.25) has data; the rest are missing.
    inputs = ScoreInputs(price_to_book=1.0)  # valuation=100, everything else None
    result = compute_score(inputs, WEIGHTS)

    assert result.value == pytest.approx(100.0)  # renormalized: 100% of available weight
    assert result.coverage == pytest.approx(0.25)  # only 25% of total weight had data


def test_compute_score_none_when_nothing_available() -> None:
    result = compute_score(ScoreInputs(), WEIGHTS)
    assert result.value is None
    assert result.coverage == 0.0
    assert all(c.normalized_value is None for c in result.components)
    assert all(c.contribution is None for c in result.components)


def test_compute_score_contributions_sum_to_value() -> None:
    inputs = ScoreInputs(price_to_book=1.0, debt_to_equity=0.5, gross_margins=0.20)
    result = compute_score(inputs, WEIGHTS)
    total_contribution = sum(
        c.contribution for c in result.components if c.contribution is not None
    )
    assert total_contribution == pytest.approx(result.value)


def test_compute_score_unknown_component_key_is_treated_as_missing() -> None:
    result = compute_score(ScoreInputs(price_to_book=1.0), {**WEIGHTS, "nonexistent": 0.10})
    assert result.coverage == pytest.approx(0.25 / 1.10)
