import pytest

from app.services.indian_units import (
    RUPEE_METRICS,
    SHARE_COUNT_METRICS,
    format_count_prose,
    format_inr_prose,
    format_metric_for_prose,
)


def test_format_inr_prose_uses_lakh_crore_for_trillion_scale() -> None:
    # 1.6 trillion == 1.6 lakh crore, the exact live example that prompted
    # this module (a raw marketCap the model narrated as "$1.6 trillion").
    assert format_inr_prose(1.6e12) == "₹1.60 lakh crore"


def test_format_inr_prose_uses_crore_for_hundred_crore_scale() -> None:
    assert format_inr_prose(4_523 * 1e7) == "₹4,523 crore"


def test_format_inr_prose_uses_lakh_for_smaller_amounts() -> None:
    assert format_inr_prose(85 * 1e5) == "₹85.00 lakh"


def test_format_inr_prose_uses_plain_rupees_below_a_lakh() -> None:
    assert format_inr_prose(45_000) == "₹45,000"


def test_format_inr_prose_handles_negative_values() -> None:
    assert format_inr_prose(-1.6e12) == "-₹1.60 lakh crore"


def test_format_inr_prose_returns_none_for_none() -> None:
    assert format_inr_prose(None) is None


def test_format_count_prose_uses_crore_and_lakh_for_share_counts() -> None:
    assert format_count_prose(2.71 * 1e7, unit="shares") == "2.71 crore shares"
    assert format_count_prose(50 * 1e5, unit="shares") == "50.00 lakh shares"
    assert format_count_prose(4_000, unit="shares") == "4,000 shares"


def test_format_metric_for_prose_converts_market_cap() -> None:
    assert format_metric_for_prose("marketCap", 1.6e12) == "₹1.60 lakh crore"


def test_format_metric_for_prose_converts_share_counts() -> None:
    assert format_metric_for_prose("sharesOutstanding", 2.71e7) == "2.71 crore shares"
    assert format_metric_for_prose("floatShares", 2.71e7) == "2.71 crore shares"


def test_format_metric_for_prose_leaves_ratios_unchanged() -> None:
    """A ratio, percentage, or multiple must pass through as a bare
    number — running it through lakh/crore conversion would misrepresent
    a dimensionless figure as a rupee amount."""
    assert format_metric_for_prose("trailingPE", 23.8) == "23.8"
    assert format_metric_for_prose("debtToEquity", 36.65) == "36.65"


def test_format_metric_for_prose_reports_unavailable_for_a_missing_rupee_value() -> None:
    assert format_metric_for_prose("marketCap", None) == "unavailable"


def test_rupee_and_share_count_metric_sets_do_not_overlap() -> None:
    assert RUPEE_METRICS.isdisjoint(SHARE_COUNT_METRICS)


@pytest.mark.parametrize("value", [0, 1, 999.99])
def test_format_inr_prose_never_raises_on_small_or_zero_values(value: float) -> None:
    format_inr_prose(value)  # must not raise
