"""Computes the technical snapshot + a compact charting series for a company page."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.engines.indicators import drawdown_series, historical_volatility, macd, rsi, sma
from app.services.adjusted_prices import get_adjusted_bars


@dataclass(frozen=True, slots=True)
class TechnicalSnapshot:
    as_of: dt.date | None
    close: float | None
    dma20: float | None
    dma50: float | None
    dma100: float | None
    dma200: float | None
    rsi14: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    volatility20: float | None
    drawdown_pct: float | None


@dataclass(frozen=True, slots=True)
class TechnicalSeries:
    dates: list[dt.date]
    close: list[float]
    dma20: list[float | None]
    dma50: list[float | None]
    dma100: list[float | None]
    dma200: list[float | None]


@dataclass(frozen=True, slots=True)
class TechnicalsResult:
    snapshot: TechnicalSnapshot
    series: TechnicalSeries
    price_source: str


_EMPTY_SNAPSHOT = TechnicalSnapshot(
    as_of=None,
    close=None,
    dma20=None,
    dma50=None,
    dma100=None,
    dma200=None,
    rsi14=None,
    macd_line=None,
    macd_signal=None,
    macd_histogram=None,
    volatility20=None,
    drawdown_pct=None,
)


def compute_technicals(db: Session, asset: Asset, *, lookback_days: int = 450) -> TechnicalsResult:
    bars, price_source = get_adjusted_bars(db, asset, lookback_days=lookback_days)

    dates = [b.date for b in bars]
    closes = [b.close for b in bars]

    dma20 = sma(closes, 20)
    dma50 = sma(closes, 50)
    dma100 = sma(closes, 100)
    dma200 = sma(closes, 200)
    rsi14 = rsi(closes, 14)
    macd_result = macd(closes)
    vol20 = historical_volatility(closes, window=20)
    dd = drawdown_series(closes)

    snapshot = (
        _EMPTY_SNAPSHOT
        if not closes
        else TechnicalSnapshot(
            as_of=dates[-1],
            close=closes[-1],
            dma20=dma20[-1],
            dma50=dma50[-1],
            dma100=dma100[-1],
            dma200=dma200[-1],
            rsi14=rsi14[-1],
            macd_line=macd_result.macd_line[-1],
            macd_signal=macd_result.signal_line[-1],
            macd_histogram=macd_result.histogram[-1],
            volatility20=vol20[-1],
            drawdown_pct=dd[-1],
        )
    )

    series = TechnicalSeries(
        dates=dates, close=closes, dma20=dma20, dma50=dma50, dma100=dma100, dma200=dma200
    )
    return TechnicalsResult(snapshot=snapshot, series=series, price_source=price_source)
