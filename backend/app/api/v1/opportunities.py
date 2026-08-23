"""Opportunity Finder endpoints (Build_plan.md §J/§K)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.engines.opportunity.registry import SCREEN_LABELS, SCREENS
from app.services.opportunities import run_screen

router = APIRouter(tags=["opportunities"])


def _envelope(data: object, *, source: str, confidence: str = "high") -> dict:
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": source,
            "confidence": confidence,
        },
    }


@router.get("/opportunities/screens")
def list_screens() -> dict:
    data = [{"id": screen_id, "label": SCREEN_LABELS[screen_id]} for screen_id in SCREENS]
    return _envelope(data, source="static")


@router.get("/opportunities")
def get_opportunities(
    screen: str = Query(...), db: Session = Depends(get_db)
) -> dict:
    if screen not in SCREENS:
        raise HTTPException(status_code=400, detail=f"unknown screen: {screen!r}")

    hits = run_screen(db, screen)
    data = [
        {
            "symbol": h.asset.symbol,
            "exchange": h.asset.exchange,
            "name": h.asset.name,
            "screen_id": h.screen_id,
            "metrics": h.metrics,
        }
        for h in hits
    ]
    return _envelope(data, source="db", confidence="high" if data else "low")
