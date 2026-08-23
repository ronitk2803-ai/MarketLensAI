"""Search + company-page endpoints (Build_plan.md §J).

Thin HTTP layer only: validation, DB session, envelope shaping. All
orchestration (cache -> provider -> engine -> persist) lives in services.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.db.session import get_db
from app.services.adjusted_prices import get_adjusted_bars
from app.services.corporate_actions import get_or_fetch_corporate_actions
from app.services.fundamentals import get_or_fetch_ratios, get_or_fetch_statements
from app.services.news import get_or_fetch_news
from app.services.scoring import get_or_compute_score
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


def _validate_range(range: str) -> int:
    if range not in RANGE_TO_DAYS:
        raise HTTPException(status_code=400, detail=f"unsupported range: {range!r}")
    return RANGE_TO_DAYS[range]


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
    # A short lookback is enough for "latest + previous close" without
    # paying for a year of history just to render the header.
    bars, price_source = get_adjusted_bars(db, asset, lookback_days=10)

    latest = bars[-1] if bars else None
    previous = bars[-2] if len(bars) >= 2 else None
    change_pct = (
        (latest.close - previous.close) / previous.close * 100
        if latest is not None and previous is not None and previous.close
        else None
    )

    data = {
        "symbol": asset.symbol,
        "exchange": asset.exchange,
        "name": asset.name,
        "sector": asset.company.sector if asset.company else None,
        "industry": (
            asset.company.industry.name if asset.company and asset.company.industry else None
        ),
        "latest_price": {
            "date": latest.date if latest else None,
            "close": latest.close if latest else None,
            "change_pct": change_pct,
        },
    }
    confidence = "high" if latest is not None else "low"
    return _envelope(data, source=price_source, confidence=confidence)


@router.get("/companies/{symbol}/prices")
def get_prices(
    symbol: str, range: str = Query(default="1y", alias="range"), db: Session = Depends(get_db)
) -> dict:
    lookback_days = _validate_range(range)
    asset = _get_asset_or_404(db, symbol)

    bars, price_source = get_adjusted_bars(db, asset, lookback_days=lookback_days)
    data = [
        {
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    confidence = "high" if data else "low"
    return _envelope(data, source=price_source, confidence=confidence)


@router.get("/companies/{symbol}/corporate-actions")
def get_corporate_actions(symbol: str, db: Session = Depends(get_db)) -> dict:
    asset = _get_asset_or_404(db, symbol)
    actions = get_or_fetch_corporate_actions(db, asset)
    data = [
        {"ex_date": a.ex_date, "type": a.type, "ratio": a.ratio, "amount": a.amount}
        for a in actions
    ]
    return _envelope(data, source="yfinance_actions", confidence="high" if data else "low")


@router.get("/companies/{symbol}/fundamentals")
def get_fundamentals(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Best-effort fundamentals (Build_plan.md §7/§H) — every field carries
    its own confidence; a missing field is omitted, never guessed."""
    asset = _get_asset_or_404(db, symbol)

    ratio_rows = get_or_fetch_ratios(db, asset)
    statement_rows = get_or_fetch_statements(db, asset, "income", "FY")

    periods: dict[str, dict] = {}
    for row in statement_rows:
        period = periods.setdefault(
            row.period_end.isoformat(),
            {"period_end": row.period_end, "period_type": row.period_type, "line_items": {}},
        )
        period["line_items"][row.line_item] = float(row.value)

    data = {
        "ratios": [
            {
                "metric": row.metric,
                "value": float(row.value),
                "source": row.source,
                "confidence": row.confidence,
            }
            for row in ratio_rows
        ],
        "income_statement": sorted(
            periods.values(), key=lambda p: p["period_end"], reverse=True
        ),
    }
    # Always "low": even a successful fetch here is single-source and
    # uncross-checked (Build_plan.md §6/§H) — finding data doesn't earn it
    # more trust than the source itself has.
    return _envelope(data, source="yfinance_fundamentals", confidence="low")


@router.get("/companies/{symbol}/news")
def get_news(symbol: str, db: Session = Depends(get_db)) -> dict:
    asset = _get_asset_or_404(db, symbol)
    articles = get_or_fetch_news(db, asset)
    data = [
        {
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "title": a.title,
        }
        for a in articles
    ]
    return _envelope(data, source="google_news", confidence="high" if data else "low")


@router.get("/companies/{symbol}/score")
def get_score(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Opportunity Score (Build_plan.md §L) — research attractiveness /
    opportunity characteristics, never a return prediction (enforced in
    copy at the frontend layer too)."""
    asset = _get_asset_or_404(db, symbol)
    score, components = get_or_compute_score(db, asset)

    data = {
        "value": float(score.value) if score.value is not None else None,
        "coverage": float(score.coverage),
        "as_of": score.as_of,
        "components": [
            {
                "component": c.component,
                "normalized_value": (
                    float(c.normalized_value) if c.normalized_value is not None else None
                ),
                "weight": float(c.weight),
                "contribution": float(c.contribution) if c.contribution is not None else None,
            }
            for c in components
        ],
    }
    return _envelope(data, source="mlai_scoring_v1", confidence=score.confidence)


@router.get("/companies/{symbol}/technicals")
def get_technicals(
    symbol: str, range: str = Query(default="1y", alias="range"), db: Session = Depends(get_db)
) -> dict:
    lookback_days = _validate_range(range)
    asset = _get_asset_or_404(db, symbol)

    result = compute_technicals(db, asset, lookback_days=lookback_days)
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
