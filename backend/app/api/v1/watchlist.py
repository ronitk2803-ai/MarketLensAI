"""Multi-symbol quote panel (see app/services/watchlist.py for why this has
no server-side persistence — the frontend supplies the symbol list on every
call from its own localStorage)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.watchlist import RangeStat, get_watchlist_quotes

router = APIRouter(tags=["watchlist"])

MAX_SYMBOLS = 50
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


@router.get("/watchlist/quotes")
def watchlist_quotes(
    symbols: str = Query(..., description="Comma-separated NSE symbols"),
    deltas: str = Query("7,14,30", description="Comma-separated trading-session windows"),
    db: Session = Depends(get_db),
) -> dict:
    symbol_list = [s for s in symbols.split(",") if s.strip()][:MAX_SYMBOLS]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="no symbols given")

    try:
        delta_list = [int(d) for d in deltas.split(",") if d.strip()][:MAX_DELTA_WINDOWS]
    except ValueError as error:
        raise HTTPException(status_code=400, detail="deltas must be integers") from error
    if any(d <= 0 for d in delta_list):
        raise HTTPException(status_code=400, detail="delta windows must be positive")

    quotes, unknown = get_watchlist_quotes(db, symbol_list, delta_days=delta_list)

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
