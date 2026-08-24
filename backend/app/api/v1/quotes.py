"""Live quote endpoint.

Deliberately separate from /watchlist/quotes rather than folded into it.
The watchlist payload (multi-window deltas, 52-week and all-time ranges,
sparkline) is derived from full stored history and only changes once a day,
while this is polled every few seconds — merging them would mean redoing
all of that work on every tick for a number that is the only thing which
moved.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.quotes import get_live_quotes

router = APIRouter(tags=["quotes"])

MAX_SYMBOLS = 50


@router.get("/quotes")
def live_quotes(
    symbols: str = Query(..., description="Comma-separated NSE symbols"),
    db: Session = Depends(get_db),
) -> dict:
    symbol_list = [s for s in symbols.split(",") if s.strip()][:MAX_SYMBOLS]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="no symbols given")

    quotes = get_live_quotes(db, symbol_list)

    data = [
        {
            "symbol": q.asset.symbol,
            "exchange": q.asset.exchange,
            "ltp": q.ltp,
            "previous_close": q.previous_close,
            "change_pct": (
                (q.ltp - q.previous_close) / q.previous_close * 100
                if q.previous_close
                else None
            ),
            "as_of": q.as_of,
            "market_state": q.market_state,
            # The forming candle. Only emitted when the whole OHLC is
            # present — a partial candle would render as a misleading shape
            # (a missing open collapses it to a doji it never was).
            "day_candle": (
                {
                    "open": q.day_open,
                    "high": q.day_high,
                    "low": q.day_low,
                    "close": q.ltp,
                    "volume": q.day_volume,
                }
                if None not in (q.day_open, q.day_high, q.day_low)
                else None
            ),
        }
        for q in quotes.values()
    ]

    # "low" when nothing came back: the caller is about to render stored
    # closes instead, and the envelope should say so rather than implying
    # live coverage it doesn't have.
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": "yfinance_quotes",
            "confidence": "high" if data else "low",
        },
    }
