import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import Bar
from app.engines.indicators import rsi as rsi_fn
from app.engines.indicators import sma
from app.providers.india.nse_actions import NSECorporateActionsProvider
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.services.technicals import compute_technicals


def _make_asset(db: Session) -> Asset:
    asset = Asset(symbol="ZZTECH1", exchange="NSE", market="IN", name="Test Technicals Co")
    db.add(asset)
    db.flush()
    return asset


def _linear_bars(n: int) -> list[Bar]:
    today = dt.date.today()
    return [
        Bar(
            date=today - dt.timedelta(days=n - 1 - i),
            open=100 + i,
            high=100 + i,
            low=100 + i,
            close=100.0 + i,
            volume=1000 + i,
        )
        for i in range(n)
    ]


def test_compute_technicals_matches_indicators_computed_directly(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration check on orchestration, not on the math (already unit
    tested in test_indicators_*.py): the snapshot/series must equal calling
    the indicator functions directly on the same close series."""
    asset = _make_asset(db)
    bars = _linear_bars(60)

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: bars)
    monkeypatch.setattr(
        NSECorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )

    result = compute_technicals(db, asset, lookback_days=90)

    closes = [b.close for b in bars]
    assert result.series.close == closes
    assert result.series.dma20 == sma(closes, 20)
    assert result.series.dma50 == sma(closes, 50)
    assert result.snapshot.close == closes[-1]
    assert result.snapshot.dma20 == sma(closes, 20)[-1]
    assert result.snapshot.rsi14 == rsi_fn(closes, 14)[-1]
    assert result.price_source == "nse_bhavcopy"


def test_compute_technicals_empty_when_no_price_data(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: [])
    monkeypatch.setattr(
        NSECorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )

    result = compute_technicals(db, asset)

    assert result.snapshot.close is None
    assert result.snapshot.as_of is None
    assert result.series.dates == []
