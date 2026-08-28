import pytest

from app.engines.scoring.aggregate import compute_score
from app.engines.scoring.base import ScoreInputs
from app.engines.scoring.components import (
    COMPONENT_FUNCS,
    earnings_valuation,
    fundamental_quality,
    growth,
    participation,
    technical_setup,
    valuation,
)
from app.engines.scoring.registry import DEFAULT_WEIGHTS, SEED_PROFILES


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
    # debt_to_equity is Yahoo's PERCENTAGE unit: 10.0 == 0.1x.
    debt_only = fundamental_quality(ScoreInputs(debt_to_equity=10.0))
    assert debt_only == pytest.approx(100.0)
    margin_only = fundamental_quality(ScoreInputs(gross_margins=0.40))
    assert margin_only == pytest.approx(100.0)
    both = fundamental_quality(ScoreInputs(debt_to_equity=10.0, gross_margins=0.40))
    assert both == pytest.approx(100.0)
    both_floor = fundamental_quality(ScoreInputs(debt_to_equity=150.0, gross_margins=0.0))
    assert both_floor == pytest.approx(0.0)


def test_fundamental_quality_reads_debt_to_equity_as_a_percentage() -> None:
    """Regression: Yahoo returns debtToEquity as a percentage (live Nifty
    500 median ~23.8 == 0.24x), but this was normalized as if it were a
    ratio — which scored any D/E >= 3% as zero and pinned 379 of 458
    companies (82.8%) at 0 on the leverage leg."""
    typical = fundamental_quality(ScoreInputs(debt_to_equity=23.8))
    assert typical is not None
    assert typical > 80.0  # a middling-leverage company is not a zero

    # The band's endpoints, in the source's own unit.
    assert fundamental_quality(ScoreInputs(debt_to_equity=10.0)) == pytest.approx(100.0)
    assert fundamental_quality(ScoreInputs(debt_to_equity=150.0)) == pytest.approx(0.0)
    assert fundamental_quality(ScoreInputs(debt_to_equity=80.0)) == pytest.approx(50.0)

    # Genuinely leveraged names still score at the floor.
    assert fundamental_quality(ScoreInputs(debt_to_equity=181.0)) == pytest.approx(0.0)


def test_fundamental_quality_none_when_both_missing() -> None:
    assert fundamental_quality(ScoreInputs()) is None


def test_earnings_valuation_rewards_lower_pe() -> None:
    assert earnings_valuation(ScoreInputs(trailing_pe=15.0)) == pytest.approx(100.0)
    assert earnings_valuation(ScoreInputs(trailing_pe=60.0)) == pytest.approx(0.0)
    assert earnings_valuation(ScoreInputs(trailing_pe=37.5)) == pytest.approx(50.0)
    assert earnings_valuation(ScoreInputs(trailing_pe=5.0)) == pytest.approx(100.0)
    assert earnings_valuation(ScoreInputs(trailing_pe=500.0)) == pytest.approx(0.0)


def test_earnings_valuation_none_for_missing_or_non_positive_pe() -> None:
    """A loss-making company has no multiple, not a cheap one — scoring a
    negative P/E as 100 would invert the signal entirely."""
    assert earnings_valuation(ScoreInputs()) is None
    assert earnings_valuation(ScoreInputs(trailing_pe=0.0)) is None
    assert earnings_valuation(ScoreInputs(trailing_pe=-12.0)) is None


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


# The real seeded weights, not a copy — a drifting duplicate would let the
# engine and the profile it's actually scored with disagree silently.
WEIGHTS = DEFAULT_WEIGHTS


def test_compute_score_full_coverage() -> None:
    inputs = ScoreInputs(
        price_to_book=1.0,  # valuation=100
        debt_to_equity=10.0,
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
    inputs = ScoreInputs(price_to_book=1.0, debt_to_equity=10.0, gross_margins=0.20)
    result = compute_score(inputs, WEIGHTS)
    total_contribution = sum(
        c.contribution for c in result.components if c.contribution is not None
    )
    assert total_contribution == pytest.approx(result.value)


def test_compute_score_unknown_component_key_is_treated_as_missing() -> None:
    result = compute_score(ScoreInputs(price_to_book=1.0), {**WEIGHTS, "nonexistent": 0.10})
    assert result.coverage == pytest.approx(0.25 / 1.10)


def test_every_seeded_profile_weight_key_resolves_to_a_real_component() -> None:
    """The failure mode this guards is silent, not loud: compute_score
    treats an unknown weight key as missing data *and* still counts it
    toward total weight, so a typo'd or not-yet-implemented component just
    quietly depresses coverage for every asset on that profile."""
    for industry_code, weights in SEED_PROFILES.items():
        unknown = set(weights) - set(COMPONENT_FUNCS)
        assert not unknown, f"profile {industry_code} references unknown component(s): {unknown}"


def test_every_seeded_profile_sums_to_one() -> None:
    for industry_code, weights in SEED_PROFILES.items():
        assert sum(weights.values()) == pytest.approx(1.0), industry_code


def test_valuation_prefers_the_peer_percentile_over_the_absolute_band() -> None:
    # A P/B of 3.5 alone scores 50 on the absolute band (see the first
    # test above), but a precomputed percentile of 90 must win outright —
    # gather_score_inputs already oriented it (higher = cheaper-than-peers)
    # by the time it reaches ScoreInputs.
    result = valuation(ScoreInputs(price_to_book=3.5, price_to_book_percentile=90.0))
    assert result == pytest.approx(90.0)


def test_valuation_falls_back_to_absolute_band_without_a_percentile() -> None:
    assert valuation(ScoreInputs(price_to_book=3.5)) == pytest.approx(50.0)


def test_fundamental_quality_prefers_percentile_leg_by_leg() -> None:
    # Debt leg has a percentile (used directly); margin leg doesn't (falls
    # back to the absolute band) — both legs blend as normal.
    result = fundamental_quality(
        ScoreInputs(debt_to_equity_percentile=80.0, gross_margins=0.40)
    )
    assert result == pytest.approx((80.0 + 100.0) / 2)


def test_earnings_valuation_prefers_percentile_but_still_excludes_non_positive_pe() -> None:
    assert earnings_valuation(
        ScoreInputs(trailing_pe=25.0, trailing_pe_percentile=70.0)
    ) == pytest.approx(70.0)
    # A percentile computed some other way must never override a
    # non-positive P/E — that company has no multiple, peer-relative or not.
    assert earnings_valuation(
        ScoreInputs(trailing_pe=-10.0, trailing_pe_percentile=70.0)
    ) is None


def test_growth_prefers_percentile_leg_by_leg() -> None:
    result = growth(
        ScoreInputs(revenue_growth_percentile=90.0, earnings_growth=0.0)
    )
    assert result == pytest.approx((90.0 + 50.0) / 2)


def test_financials_profile_drops_fundamental_quality_and_keeps_technicals_comparable() -> None:
    """The two design claims that justify this profile existing at all: it
    excludes the component whose legs are structurally invalid for a
    lender, and it leaves the technical half identical to default so that
    half of the score stays comparable across industries."""
    financials = SEED_PROFILES["financials"]
    assert "fundamental_quality" not in financials
    assert "earnings_valuation" in financials
    for shared in ("technical_setup", "participation"):
        assert financials[shared] == DEFAULT_WEIGHTS[shared]
