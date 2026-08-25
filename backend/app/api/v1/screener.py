"""Combinable screener endpoints (Build_plan.md §J:326's `POST
/screener/run`, §K's AND/OR condition tree, P2 step 22).

Separate from GET /opportunities rather than folded into it: that
endpoint's `screen` is required and its whole contract is one preset at a
time, which the homepage's four boards and the preset pills depend on.

Sign-in required. This is the most expensive endpoint in the app — a full
universe scan at up to ~300 sessions — and §J:329 calls for rate-limiting
it. There is no rate limiter in this app, so the auth gate is what
actually bounds abuse; the structural limits below bound legibility and
payload size, not cost. Cost is O(distinct metrics x universe), dominated
by the deepest metric's required_bars.
"""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models import AppUser
from app.db.session import get_db
from app.engines.opportunity.conditions import Condition, Group, Node
from app.services.metric_registry import METRIC_KEYS, REGISTRY
from app.services.opportunities import list_industries
from app.services.screener import run_condition_screen

router = APIRouter(prefix="/screener", tags=["screener"])

MAX_DEPTH = 4
MAX_CONDITIONS = 12
MAX_CHILDREN = 10

# `eq` is deliberately absent. evaluate_trigger compares with ==, and an
# exact float match against a computed indicator (rsi14 eq 30) can never
# be true — a user would get zero rows with no way to tell why.
ScreenerOperator = Literal["gt", "lt", "gte", "lte"]


class ConditionModel(BaseModel):
    metric: str
    operator: ScreenerOperator
    threshold: float


class GroupModel(BaseModel):
    op: Literal["and", "or"]
    # An empty group is vacuously true for AND, which would silently return
    # the entire universe.
    children: list["GroupModel | ConditionModel"] = Field(min_length=1, max_length=MAX_CHILDREN)


# Explicit rather than left to Pydantic's lazy resolution, so a broken
# forward reference fails at import rather than on the first request.
GroupModel.model_rebuild()


class ScreenerRequest(BaseModel):
    tree: GroupModel
    industry: str | None = None

    @model_validator(mode="after")
    def _within_structural_limits(self) -> "ScreenerRequest":
        """Walked with an explicit stack rather than recursion — the depth
        cap exists precisely because the input is untrusted, so the
        validator must not itself be the thing that blows the stack.

        Structural limits are 422 (the shape is wrong); unknown metric and
        industry names are 400, raised in the endpoint, matching
        theses.py's _validate_metrics and opportunities.py's screen check.
        """
        conditions = 0
        stack: list[tuple[GroupModel | ConditionModel, int]] = [(self.tree, 1)]
        while stack:
            node, depth = stack.pop()
            if depth > MAX_DEPTH:
                raise ValueError(f"condition tree is nested deeper than {MAX_DEPTH} levels")
            if isinstance(node, ConditionModel):
                conditions += 1
                if conditions > MAX_CONDITIONS:
                    raise ValueError(f"more than {MAX_CONDITIONS} conditions")
                continue
            for child in node.children:
                stack.append((child, depth + 1))
        if conditions == 0:
            raise ValueError("at least one condition is required")
        return self


def _to_node(model: GroupModel | ConditionModel) -> Node:
    """Pydantic request shape -> the pure engine's own dataclasses, so the
    engine never depends on the API layer."""
    if isinstance(model, ConditionModel):
        return Condition(metric=model.metric, operator=model.operator, threshold=model.threshold)
    return Group(op=model.op, children=[_to_node(child) for child in model.children])


def _collect_metric_names(model: GroupModel | ConditionModel) -> set[str]:
    if isinstance(model, ConditionModel):
        return {model.metric}
    names: set[str] = set()
    for child in model.children:
        names |= _collect_metric_names(child)
    return names


@router.get("/metrics")
def get_metrics() -> dict:
    """The screenable/triggerable vocabulary, served rather than
    duplicated: the same list is otherwise hardcoded in the frontend's
    thesis form and would drift the moment either side changed. `unit` is
    what lets a threshold input say whether 15 means 15% or 1500%."""
    data = [
        {
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "group": spec.group,
            "required_bars": spec.required_bars,
        }
        for spec in sorted(REGISTRY.values(), key=lambda s: (s.group, s.label))
    ]
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": "static",
            "confidence": "high",
        },
    }


@router.post("/run")
def run(
    payload: ScreenerRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    unknown = sorted(_collect_metric_names(payload.tree) - METRIC_KEYS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown metric(s): {', '.join(unknown)}")
    if payload.industry is not None and payload.industry not in {
        code for code, _ in list_industries(db)
    }:
        raise HTTPException(status_code=400, detail=f"unknown industry: {payload.industry!r}")

    result = run_condition_screen(db, _to_node(payload.tree), industry=payload.industry)

    data = [
        {
            "symbol": r.hit.asset.symbol,
            "exchange": r.hit.asset.exchange,
            "name": r.hit.asset.name,
            "screen_id": r.hit.screen_id,
            "metrics": r.hit.metrics,
            "rank": r.rank,
            "opportunity_score": r.opportunity_score,
            "spark": result.sparklines.get(r.hit.asset.symbol, []),
            "industry": result.industries.get(r.hit.asset.symbol, ("", None))[1],
        }
        for r in result.ranked
    ]
    # Unlike opportunities.py's `"high" if data else "low"`, an empty
    # result from a well-covered tree is a *confident* empty — what makes
    # a result untrustworthy is missing inputs, not missing matches.
    fully_covered = all(c.available == c.total for c in result.coverage)
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": "db",
            "confidence": "high" if fully_covered else "low",
            "universe_size": result.universe_size,
            "coverage": [
                {"metric": c.metric, "available": c.available, "total": c.total}
                for c in result.coverage
            ],
        },
    }
