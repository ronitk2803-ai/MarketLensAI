"""Combinable condition trees (Build_plan.md §K: "Combinable conditions
expressed as an AND/OR tree") — pure, no IO.

A leaf is one `metric operator threshold` comparison, evaluated by
app/engines/thesis/base.py's evaluate_trigger (imported, not
re-implemented — the screener and the thesis tracker compare values the
same way by construction). A branch joins children with AND or OR.
"""

from dataclasses import dataclass
from typing import Literal

from app.engines.thesis.base import Operator, evaluate_trigger

GroupOp = Literal["and", "or"]


@dataclass(frozen=True, slots=True)
class Condition:
    metric: str
    operator: Operator
    threshold: float


@dataclass(frozen=True, slots=True)
class Group:
    op: GroupOp
    children: list["Group | Condition"]


Node = Group | Condition


def evaluate_node(node: Node, values: dict[str, float | None]) -> bool | None:
    """Three-valued (strong Kleene) evaluation. `values` maps metric key ->
    that asset's value, with None for "we have no figure for this".

    This is exactly SQL's WHERE-with-NULL, which is what every screener a
    user has already used implements:

      AND  False if ANY child is False, even alongside a None -- an asset
           that definitively fails one leg is not a match no matter what
           is unknown elsewhere. Otherwise None if anything is unknown.
      OR   True if ANY child is True, even alongside a None -- 30% revenue
           growth matches "revenue_growth gt 0.15 OR earnings_growth gt
           0.15" whether or not the earnings figure exists. Otherwise
           None if anything is unknown.

    The alternative (any unknown child poisons the whole group) is also
    sound but strictly discards answers we already hold, and it inverts
    what OR means to a user: adding an OR branch could only ever shrink
    the result set when data is sparse.
    """
    if isinstance(node, Condition):
        return evaluate_trigger(node.operator, node.threshold, values.get(node.metric))

    results = [evaluate_node(child, values) for child in node.children]
    if node.op == "and":
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    if any(r is True for r in results):
        return True
    return None if any(r is None for r in results) else False


def matches(node: Node, values: dict[str, float | None]) -> bool:
    """A row is included only on a definite True. An unknown (None) result
    excludes -- but the caller is expected to report per-metric coverage
    alongside the results, because "no data" and "no match" being
    indistinguishable is exactly what this codebase refuses to do
    silently elsewhere."""
    return evaluate_node(node, values) is True


def collect_metrics(node: Node) -> set[str]:
    """Every metric key the tree references. Drives both which columns get
    resolved and how far back the universe is loaded — so a cheap tree
    stays cheap (`close lt 100` reads ~30 sessions, not the ~300 a
    dma200_gap_pct condition would force). Defaulting that window to the
    max over ALL known metrics would quietly destroy that property."""
    if isinstance(node, Condition):
        return {node.metric}
    metrics: set[str] = set()
    for child in node.children:
        metrics |= collect_metrics(child)
    return metrics
