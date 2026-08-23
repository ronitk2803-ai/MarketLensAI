"""Search + company-page endpoints (Build_plan.md §J).

Thin HTTP layer only: validation, DB session, envelope shaping. All
orchestration (cache -> provider -> engine -> persist) lives in services.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.db.session import get_db
from app.services.search import search_assets
from app.services.technicals import compute_technicals

router = APIRouter(tags=["companies"])

RANGE_TO_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365, "5y": 365 * 5}


def _envelope(data: object, *, source: str, confidence: str = "high") -> dict:
    return {
        "data": data,
        "meta": {
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "source": source,
            "confidence": confidence,
        },
    }


def _get_asset_or_404(db: Session, symbol: str) -> Asset:
    asset = (
        db.query(Asset)
        .filter_by(symbol=symbol.upper(), market="IN", active=True)
        .one_or_none()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail=f"unknown asset: {symbol}")
    return asset


@router.get("/assets/search")
def search(q: str = Query(min_length=1), db: Session = Depends(get_db)) -> dict:
    assets = search_assets(db, q)
    data = [
        {"symbol": a.symbol, "exchange": a.exchange, "name": a.name, "isin": a.isin}
        for a in assets
    ]
    return _envelope(data, source="db")


@router.get("/companies/{symbol}")
def get_company(symbol: str, db: Session = Depends(get_db)) -> dict:
    asset = _get_asset_or_404(db, symbol)
    result = compute_technicals(db, asset, lookback_days=30)
    snapshot = result.snapshot

    data = {
        "symbol": asset.symbol,
        "exchange": asset.exchange,
        "name": asset.name,
        "sector": asset.company.sector if asset.company else None,
        "industry": (
            asset.company.industry.name if asset.company and asset.company.industry else None
        ),
        "latest_price": {"date": snapshot.as_of, "close": snapshot.close},
    }
    confidence = "high" if snapshot.close is not None else "low"
    return _envelope(data, source=result.price_source, confidence=confidence)


@router.get("/companies/{symbol}/prices")
def get_prices(
    symbol: str, range: str = Query(default="1y", alias="range"), db: Session = Depends(get_db)
) -> dict:
    if range not in RANGE_TO_DAYS:
        raise HTTPException(status_code=400, detail=f"unsupported range: {range!r}")
    asset = _get_asset_or_404(db, symbol)

    result = compute_technicals(db, asset, lookback_days=RANGE_TO_DAYS[range])
    data = [
        {"date": date, "close": close}
        for date, close in zip(result.series.dates, result.series.close, strict=True)
    ]
    confidence = "high" if data else "low"
    return _envelope(data, source=result.price_source, confidence=confidence)


@router.get("/companies/{symbol}/technicals")
def get_technicals(
    symbol: str, range: str = Query(default="1y", alias="range"), db: Session = Depends(get_db)
) -> dict:
    if range not in RANGE_TO_DAYS:
        raise HTTPException(status_code=400, detail=f"unsupported range: {range!r}")
    asset = _get_asset_or_404(db, symbol)

    result = compute_technicals(db, asset, lookback_days=RANGE_TO_DAYS[range])
    s = result.snapshot
    data = {
        "latest": {
            "as_of": s.as_of,
            "close": s.close,
            "dma20": s.dma20,
            "dma50": s.dma50,
            "dma100": s.dma100,
            "dma200": s.dma200,
            "rsi14": s.rsi14,
            "macd_line": s.macd_line,
            "macd_signal": s.macd_signal,
            "macd_histogram": s.macd_histogram,
            "volatility20": s.volatility20,
            "drawdown_pct": s.drawdown_pct,
        },
        "series": {
            "dates": result.series.dates,
            "close": result.series.close,
            "dma20": result.series.dma20,
            "dma50": result.series.dma50,
            "dma100": result.series.dma100,
            "dma200": result.series.dma200,
        },
    }
    confidence = "high" if s.close is not None else "low"
    return _envelope(data, source=result.price_source, confidence=confidence)
