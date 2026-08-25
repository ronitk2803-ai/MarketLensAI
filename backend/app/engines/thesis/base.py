"""Thesis-trigger evaluation (Build_plan.md §X.1) — pure, no IO, same
"engines are deterministic and unit-testable" convention as
app/engines/opportunity/base.py's Screen. Resolving *what* the current
value of a metric is (the actual database/computation work) belongs in
app/services/metric_registry.py; this module only knows how to compare an
already-resolved value against a threshold.
"""

from typing import Literal

Operator = Literal["gt", "lt", "gte", "lte", "eq"]

_OPERATORS = {
    "gt": lambda observed, threshold: observed > threshold,
    "lt": lambda observed, threshold: observed < threshold,
    "gte": lambda observed, threshold: observed >= threshold,
    "lte": lambda observed, threshold: observed <= threshold,
    "eq": lambda observed, threshold: observed == threshold,
}


def evaluate_trigger(
    operator: Operator, threshold: float, observed_value: float | None
) -> bool | None:
    """None means "cannot evaluate" (Build_plan.md §X.1's edge case: a
    missing metric must never silently read as "not breached," which
    would be indistinguishable from a genuinely healthy trigger) — the
    caller does nothing with a None result rather than treating it as a
    real answer."""
    if observed_value is None:
        return None
    return _OPERATORS[operator](observed_value, threshold)
