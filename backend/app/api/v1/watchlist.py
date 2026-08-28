"""A signed-in user's watchlist — membership (app/services/watchlist.py's
get/add/remove_*) plus quotes for whatever's on it (get_watchlist_quotes,
unchanged from before accounts existed)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_current_verified_user
from app.db.models import AppUser
from app.db.session import get_db
from app.services.watchlist import (
    RangeStat,
    add_to_watchlist,
    get_watchlist_quotes,
    get_watchlist_symbols,
    remove_from_watchlist,
)

router = APIRouter(tags=["watchlist"])

MAX_DELTA_WINDOWS = 3


def _envelope(data: object, *, source: str, confidence: str = "high") -> dict:
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": source,
            "confidence": confidence,
        },
    }


def _range_stat_to_dict(stat: RangeStat | None) -> dict | None:
    if stat is None:
        return None
    return {"high": stat.high, "low": stat.low, "position": stat.position, "since": stat.since}


def _parse_deltas(deltas: str) -> list[int]:
    try:
        delta_list = [int(d) for d in deltas.split(",") if d.strip()][:MAX_DELTA_WINDOWS]
    except ValueError as error:
        raise HTTPException(status_code=400, detail="deltas must be integers") from error
    if any(d <= 0 for d in delta_list):
        raise HTTPException(status_code=400, detail="delta windows must be positive")
    return delta_list


@router.get("/watchlist")
def watchlist(
    deltas: str = Query("7,14,30", description="Comma-separated trading-session windows"),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    delta_list = _parse_deltas(deltas)
    symbols = get_watchlist_symbols(db, current_user.id)

    if not symbols:
        return _envelope({"quotes": [], "unknown_symbols": []}, source="db", confidence="low")

    quotes, unknown = get_watchlist_quotes(db, symbols, delta_days=delta_list)
    data = {
        "quotes": [
            {
                "symbol": q.symbol,
                "exchange": q.exchange,
                "name": q.name,
                "as_of": q.as_of,
                "close": q.close,
                "deltas": {str(n): pct for n, pct in q.deltas.items()},
                "all_time": _range_stat_to_dict(q.all_time),
                "week_52": _range_stat_to_dict(q.week_52),
                "spark": q.spark,
            }
            for q in quotes
        ],
        "unknown_symbols": unknown,
    }
    return _envelope(data, source="db", confidence="high" if quotes else "low")


@router.post("/watchlist/{symbol}")
def add_watchlist_item(
    symbol: str,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    added = add_to_watchlist(db, current_user.id, symbol)
    if not added:
        raise HTTPException(status_code=404, detail=f"unknown asset: {symbol}")
    return {"status": "ok"}


@router.delete("/watchlist/{symbol}")
def remove_watchlist_item(
    symbol: str,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    remove_from_watchlist(db, current_user.id, symbol)
    return {"status": "ok"}
