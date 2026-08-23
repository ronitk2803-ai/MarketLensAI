"""Opportunity Finder endpoints (Build_plan.md §J/§K)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.engines.opportunity.registry import SCREEN_LABELS, SCREENS
from app.services.opportunities import run_ranked_screen_with_sparklines

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

    result = run_ranked_screen_with_sparklines(db, screen)
    data = [
        {
            "symbol": r.hit.asset.symbol,
            "exchange": r.hit.asset.exchange,
            "name": r.hit.asset.name,
            "screen_id": r.hit.screen_id,
            "metrics": r.hit.metrics,
            "rank": r.rank,
            "opportunity_score": r.opportunity_score,
            # Trailing closes for the row's sparkline. Comes free off the
            # bars the screen already loaded and adjusted, so it costs no
            # extra query.
            "spark": result.sparklines.get(r.hit.asset.symbol, []),
        }
        for r in result.ranked
    ]
    return _envelope(data, source="db", confidence="high" if data else "low")
