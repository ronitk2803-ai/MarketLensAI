"""Search + company-page endpoints (Build_plan.md §J).

Thin HTTP layer only: validation, DB session, envelope shaping. All
orchestration (cache -> provider -> engine -> persist) lives in services.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limited
from app.core.security import get_current_verified_user
from app.db.models import AppUser, Asset
from app.db.session import get_db
from app.engines.historical import DIMENSIONS_COMPARED, DIMENSIONS_UNAVAILABLE, Episode
from app.providers.errors import ProviderError
from app.services.adjusted_prices import get_adjusted_bars
from app.services.company_summary import generate_summary, get_cached_summary
from app.services.corporate_actions import get_or_fetch_corporate_actions
from app.services.fundamentals import (
    get_or_fetch_ratios,
    get_or_fetch_statements,
    get_sector_ratio_stats,
)
from app.services.historical_episodes import get_historical_falls
from app.services.news import get_or_fetch_news
from app.services.scoring import gather_score_inputs, get_or_compute_score
from app.services.search import search_assets
from app.services.sector_index import get_sector_pe_for_industry
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

    # For "is this P/E high or low" — a number this company's own ratios
    # can't answer alone. NSE's own sectoral-index P/E (get_sector_pe_for_industry)
    # is the authoritative figure and is tried first; it only covers 18 of
    # this app's 20 industries (see INDUSTRY_TO_NIFTY_INDEX), so the
    # remaining two — and the "forward" side, which NSE's file doesn't
    # carry at all — fall back to a median across whatever same-industry
    # companies this app happens to have fundamentals cached for
    # (get_sector_ratio_stats). None/0 always means "not enough data yet,"
    # never "this company has no peers."
    industry = asset.company.industry if asset.company else None
    industry_id = industry.id if industry else None
    industry_code = industry.code if industry else None

    nse_sector = get_sector_pe_for_industry(db, industry_code)
    forward_stats = get_sector_ratio_stats(db, industry_id, "forwardPE") if industry_id else None
    trailing_pe: float | None
    trailing_pe_source: str | None
    trailing_pe_index_name: str | None
    if nse_sector is not None and nse_sector.pe is not None:
        trailing_pe = float(nse_sector.pe)
        trailing_pe_source = "nse_index"
        trailing_pe_index_name = nse_sector.index_name
        trailing_pe_sample_size = 0
    else:
        trailing_stats = (
            get_sector_ratio_stats(db, industry_id, "trailingPE") if industry_id else None
        )
        trailing_pe = trailing_stats.median if trailing_stats else None
        trailing_pe_source = "peer_median" if trailing_stats else None
        trailing_pe_index_name = None
        trailing_pe_sample_size = trailing_stats.sample_size if trailing_stats else 0

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
        "sector_pe": {
            "trailing_pe": trailing_pe,
            "trailing_pe_source": trailing_pe_source,
            "trailing_pe_index_name": trailing_pe_index_name,
            "trailing_pe_sample_size": trailing_pe_sample_size,
            "forward_median": forward_stats.median if forward_stats else None,
            "forward_sample_size": forward_stats.sample_size if forward_stats else 0,
        },
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


@router.get("/companies/{symbol}/ai-summary")
def get_ai_summary(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Cache-only read — never triggers generation, so it's safe to load on
    every page view. `POST` (the button) is the only thing that spends an
    LLM call, and only when the cached summary is actually out of date."""
    asset = _get_asset_or_404(db, symbol)
    row = get_cached_summary(db, asset)
    data = {"summary": row.summary, "generated_at": row.generated_at} if row else None
    return _envelope(data, source="gemini_summary", confidence="low")


@router.post("/companies/{symbol}/ai-summary", dependencies=[rate_limited("ai_summary")])
def create_ai_summary(
    symbol: str,
    current_user: AppUser = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
) -> dict:
    """User-triggered generation. Cache-aware (app/services/company_summary.py):
    a click when nothing about the company changed since the last click
    reuses the cached row rather than spending another API call.

    Requires a VERIFIED account, which is a stricter bar than the rest of
    the app and than POST /screener/run, whose gate this used to share.
    The difference: a screener run is CPU we already own, while this is the
    only endpoint that can spend an LLM call against a rate-limited free
    tier. "You must own a real inbox" is the cheapest meaningful bound on
    someone burning that quota with throwaway signups; the "ai_summary"
    limiter (app/core/rate_limit.py, ~5/day per user) is the second,
    tighter one layered on top of it. Note this is not the "can't save
    anything" rule the other gated endpoints implement — nothing is saved
    on the user's behalf here; it is a cost control that happens to use
    the same dependency.

    The GET below stays public: it only ever reads the cache and is free."""
    asset = _get_asset_or_404(db, symbol)
    try:
        row = generate_summary(db, asset)
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    data = {"summary": row.summary, "generated_at": row.generated_at}
    return _envelope(data, source="gemini_summary", confidence="low")


@router.get("/companies/{symbol}/score")
def get_score(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Opportunity Score (Build_plan.md §L) — research attractiveness /
    opportunity characteristics, never a return prediction (enforced in
    copy at the frontend layer too)."""
    asset = _get_asset_or_404(db, symbol)
    score, components = get_or_compute_score(db, asset)
    # Re-derived, not stored on ScoreComponent (which deliberately keeps
    # raw_value=None — see aggregate.py: several components blend two raw
    # inputs, so there's no single scalar to store per component without
    # misrepresenting a blend as one number). Cache-first underneath
    # (technicals from stored bars, fundamentals from financial_metric), so
    # this is a read against already-stored data, not a live provider call,
    # and — because get_or_compute_score only recomputes once a day — it
    # reflects the exact inputs today's score was actually built from.
    inputs = gather_score_inputs(db, asset)

    data = {
        "value": float(score.value) if score.value is not None else None,
        "coverage": float(score.coverage),
        "as_of": score.as_of,
        # Which weighting profile scored this company (Build_plan.md §M).
        # Surfaced because profiles apply different components, so without
        # it a reader can't tell why two companies show different rows.
        "profile": {
            "industry_code": score.profile.industry_code,
            "version": score.profile.version,
        },
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
        "inputs": {
            "rsi14": inputs.rsi14,
            "drawdown_pct": inputs.drawdown_pct,
            "debt_to_equity": inputs.debt_to_equity,
            "gross_margins": inputs.gross_margins,
            "revenue_growth": inputs.revenue_growth,
            "earnings_growth": inputs.earnings_growth,
            "price_to_book": inputs.price_to_book,
            "trailing_pe": inputs.trailing_pe,
            "relative_volume": inputs.relative_volume,
            "delivery_pct": inputs.delivery_pct,
        },
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


@router.get("/companies/{symbol}/historical-events")
def get_historical_events(symbol: str, db: Session = Depends(get_db)) -> dict:
    """Past falls of 20%+ in this company's own history, and how they ended.

    Takes no `range` — unlike /prices and /technicals, the window here is
    the engine's, not the reader's: "has this happened before?" must not
    change its answer because someone clicked a different chart tab.
    """
    asset = _get_asset_or_404(db, symbol)
    result = get_historical_falls(db, asset)

    def _episode(episode: Episode) -> dict:
        return {
            "peak_date": episode.peak_date,
            "peak_close": episode.peak_close,
            "trough_date": episode.trough_date,
            "trough_close": episode.trough_close,
            "recovery_date": episode.recovery_date,
            "recovery_close": episode.recovery_close,
            "decline_pct": episode.decline_pct,
            "peak_to_trough_days": episode.peak_to_trough_days,
            "peak_to_trough_sessions": episode.peak_to_trough_sessions,
            "trough_to_recovery_days": episode.trough_to_recovery_days,
            "trough_to_recovery_sessions": episode.trough_to_recovery_sessions,
            "fall_volatility": episode.fall_volatility,
            "worst_session_pct": episode.worst_session_pct,
            "worst_session_date": episode.worst_session_date,
            "recovered": episode.recovered,
            "left_censored": episode.left_censored,
        }

    current = result.current
    data = {
        "as_of": result.as_of,
        "history_start": result.history_start,
        "min_decline_pct": result.min_decline_pct,
        "current": (
            {
                **_episode(current.episode),
                "current_drawdown_pct": current.current_drawdown_pct,
                "trough_is_latest_bar": current.trough_is_latest_bar,
            }
            if current is not None
            else None
        ),
        "comparable": [
            {**_episode(c.episode), "decline_gap_pp": c.decline_gap_pp}
            for c in result.comparable
        ],
        "past_count": result.past_count,
        "excluded_left_censored": result.excluded_left_censored,
        # Declared rather than implied: only three of Screener.md §10's
        # seven comparison dimensions are derivable from the data we hold,
        # and the reader is entitled to know which four aren't.
        "dimensions_compared": list(DIMENSIONS_COMPARED),
        "dimensions_unavailable": list(DIMENSIONS_UNAVAILABLE),
    }
    # A fall whose peak is the first bar we hold has a magnitude that's only
    # a lower bound, so the whole answer is weaker than it looks.
    confidence = (
        "low"
        if result.as_of is None or (current is not None and current.episode.left_censored)
        else "high"
    )
    return _envelope(data, source=result.price_source, confidence=confidence)
