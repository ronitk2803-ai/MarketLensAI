from app.engines.opportunity.conditions import (
    Condition,
    Group,
    collect_metrics,
    evaluate_node,
    matches,
)


def _c(metric: str, operator: str = "lt", threshold: float = 10.0) -> Condition:
    return Condition(metric=metric, operator=operator, threshold=threshold)  # type: ignore[arg-type]


def test_condition_delegates_to_evaluate_trigger() -> None:
    assert evaluate_node(_c("a", "lt", 10), {"a": 5}) is True
    assert evaluate_node(_c("a", "lt", 10), {"a": 50}) is False


def test_condition_is_none_when_the_metric_is_missing() -> None:
    assert evaluate_node(_c("a"), {}) is None
    assert evaluate_node(_c("a"), {"a": None}) is None


def test_and_is_true_only_when_every_child_is_true() -> None:
    tree = Group(op="and", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 1, "b": 2}) is True
    assert evaluate_node(tree, {"a": 1, "b": 99}) is False


def test_and_false_dominates_an_unknown() -> None:
    """A definite failure on one leg settles it — whatever is unknown
    elsewhere can't rescue a row that already failed. This is SQL's
    `NULL AND FALSE = FALSE`."""
    tree = Group(op="and", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 99, "b": None}) is False


def test_and_is_unknown_when_a_child_is_unknown_and_none_failed() -> None:
    tree = Group(op="and", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 1, "b": None}) is None


def test_or_is_true_when_any_child_is_true() -> None:
    tree = Group(op="or", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 99, "b": 1}) is True


def test_or_true_dominates_an_unknown() -> None:
    """The case that makes strict (unknown-poisons-everything) semantics
    wrong: a row that definitively satisfies one branch is a match even if
    the other branch's data is missing. Under strict, adding an OR branch
    could only ever shrink results when data is sparse."""
    tree = Group(op="or", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 1, "b": None}) is True


def test_or_is_unknown_when_nothing_matched_but_something_is_unknown() -> None:
    tree = Group(op="or", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 99, "b": None}) is None


def test_or_is_false_only_when_every_child_is_false() -> None:
    tree = Group(op="or", children=[_c("a", "lt", 10), _c("b", "lt", 10)])
    assert evaluate_node(tree, {"a": 99, "b": 99}) is False


def test_nested_groups_evaluate_recursively() -> None:
    # a AND (b OR c)
    tree = Group(
        op="and",
        children=[
            _c("a", "lt", 10),
            Group(op="or", children=[_c("b", "lt", 10), _c("c", "lt", 10)]),
        ],
    )
    assert evaluate_node(tree, {"a": 1, "b": 99, "c": 1}) is True
    assert evaluate_node(tree, {"a": 1, "b": 99, "c": 99}) is False
    assert evaluate_node(tree, {"a": 99, "b": 1, "c": 1}) is False


def test_matches_includes_only_a_definite_true() -> None:
    tree = Group(op="and", children=[_c("a", "lt", 10)])
    assert matches(tree, {"a": 1}) is True
    assert matches(tree, {"a": 99}) is False
    # Unknown excludes — but the caller reports coverage so this is
    # explicable rather than silent.
    assert matches(tree, {"a": None}) is False


def test_collect_metrics_walks_the_whole_tree() -> None:
    tree = Group(
        op="and",
        children=[
            _c("a"),
            Group(op="or", children=[_c("b"), Group(op="and", children=[_c("c")])]),
        ],
    )
    assert collect_metrics(tree) == {"a", "b", "c"}


def test_collect_metrics_deduplicates() -> None:
    tree = Group(op="or", children=[_c("a", "lt", 1), _c("a", "gt", 99)])
    assert collect_metrics(tree) == {"a"}
