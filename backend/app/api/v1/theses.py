"""Thesis Tracker endpoints (Build_plan.md §X.1, P1). Bare JSON responses,
not the {data, meta} envelope companies.py/opportunities.py use — that
envelope's meta.source/meta.confidence describe market-data provenance,
which doesn't apply to user-authored content; this follows auth.py's
precedent instead.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_current_verified_user
from app.db.models import AppUser, Thesis, ThesisEvent, ThesisTrigger
from app.db.session import get_db
from app.services.metric_registry import METRIC_KEYS
from app.services.thesis import (
    TriggerInput,
    create_thesis,
    delete_thesis,
    find_asset_by_symbol,
    get_thesis,
    list_theses,
    update_thesis,
)

router = APIRouter(prefix="/theses", tags=["theses"])

Operator = Literal["gt", "lt", "gte", "lte", "eq"]
Stance = Literal["bull", "bear", "neutral"]
Status = Literal["active", "challenged", "invalidated", "closed"]


class TriggerRequest(BaseModel):
    metric: str
    operator: Operator
    threshold: float
    description: str | None = None


class CreateThesisRequest(BaseModel):
    symbol: str
    title: str
    body: str
    stance: Stance
    conviction: int = Field(ge=1, le=5)
    triggers: list[TriggerRequest] = Field(min_length=1)


class UpdateThesisRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    stance: Stance | None = None
    conviction: int | None = Field(default=None, ge=1, le=5)
    status: Status | None = None


def _validate_metrics(triggers: list[TriggerRequest]) -> None:
    unknown = [t.metric for t in triggers if t.metric not in METRIC_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"unknown metric(s): {', '.join(unknown)}"
        )


def _trigger_to_dict(t: ThesisTrigger) -> dict:
    return {
        "id": t.id,
        "metric": t.metric,
        "operator": t.operator,
        "threshold": float(t.threshold),
        "description": t.description,
        "currently_breached": t.currently_breached,
    }


def _thesis_to_dict(t: Thesis, *, include_triggers: bool = True) -> dict:
    data = {
        "id": t.id,
        "symbol": t.asset.symbol,
        "exchange": t.asset.exchange,
        "asset_name": t.asset.name,
        "title": t.title,
        "body": t.body,
        "stance": t.stance,
        "conviction": t.conviction,
        "status": t.status,
        "created_at": t.created_at,
    }
    if include_triggers:
        data["triggers"] = [_trigger_to_dict(trig) for trig in t.triggers]
    return data


def _event_to_dict(e: ThesisEvent) -> dict:
    return {
        "id": e.id,
        "trigger_id": e.trigger_id,
        "metric": e.trigger.metric,
        "operator": e.trigger.operator,
        "threshold": float(e.trigger.threshold),
        "fired_at": e.fired_at,
        "observed_value": float(e.observed_value) if e.observed_value is not None else None,
        "note": e.note,
    }


@router.post("")
def create(
    payload: CreateThesisRequest,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict:
    _validate_metrics(payload.triggers)
    asset = find_asset_by_symbol(db, payload.symbol)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"unknown asset: {payload.symbol}")

    thesis = create_thesis(
        db,
        user_id=current_user.id,
        asset=asset,
        title=payload.title,
        body=payload.body,
        stance=payload.stance,
        conviction=payload.conviction,
        triggers=[
            TriggerInput(
                metric=t.metric,
                operator=t.operator,
                threshold=t.threshold,
                description=t.description,
            )
            for t in payload.triggers
        ],
    )
    return _thesis_to_dict(thesis)


@router.get("")
def list_mine(
    current_user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        _thesis_to_dict(t, include_triggers=False) for t in list_theses(db, current_user.id)
    ]


@router.get("/{thesis_id}")
def get_one(
    thesis_id: int,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    thesis = get_thesis(db, current_user.id, thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail="thesis not found")
    data = _thesis_to_dict(thesis)
    events = (
        db.query(ThesisEvent)
        .join(ThesisTrigger, ThesisTrigger.id == ThesisEvent.trigger_id)
        .filter(ThesisEvent.thesis_id == thesis_id)
        .order_by(ThesisEvent.fired_at.desc())
        .all()
    )
    data["events"] = [_event_to_dict(e) for e in events]
    return data


@router.put("/{thesis_id}")
def update(
    thesis_id: int,
    payload: UpdateThesisRequest,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict:
    thesis = update_thesis(
        db,
        current_user.id,
        thesis_id,
        title=payload.title,
        body=payload.body,
        stance=payload.stance,
        conviction=payload.conviction,
        status=payload.status,
    )
    if thesis is None:
        raise HTTPException(status_code=404, detail="thesis not found")
    return _thesis_to_dict(thesis)


@router.delete("/{thesis_id}")
def delete(
    thesis_id: int,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = delete_thesis(db, current_user.id, thesis_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="thesis not found")
    return {"status": "ok"}
