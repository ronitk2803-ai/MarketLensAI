from app.engines.thesis import evaluate_trigger


def test_gt_true_when_observed_exceeds_threshold() -> None:
    assert evaluate_trigger("gt", 1.5, 2.0) is True


def test_gt_false_when_observed_is_below_threshold() -> None:
    assert evaluate_trigger("gt", 1.5, 1.0) is False


def test_lt() -> None:
    assert evaluate_trigger("lt", 200.0, 150.0) is True
    assert evaluate_trigger("lt", 200.0, 250.0) is False


def test_gte_includes_equal() -> None:
    assert evaluate_trigger("gte", 5.0, 5.0) is True


def test_lte_includes_equal() -> None:
    assert evaluate_trigger("lte", 5.0, 5.0) is True


def test_eq() -> None:
    assert evaluate_trigger("eq", 0.0, 0.0) is True
    assert evaluate_trigger("eq", 0.0, 0.1) is False


def test_none_observed_value_means_cannot_evaluate() -> None:
    """Build_plan.md §X.1's edge case: missing data must never silently
    read as "not breached" — that would be indistinguishable from a
    genuinely healthy trigger. None is a third answer, not a False."""
    assert evaluate_trigger("gt", 1.5, None) is None
    assert evaluate_trigger("lt", 1.5, None) is None
