import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, PriceOHLCV
from app.services.thesis_metrics import METRIC_KEYS, resolve_metric_value


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _add_bars(db: Session, asset: Asset, closes: list[float]) -> None:
    today = dt.date.today()
    n = len(closes)
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=today - dt.timedelta(days=n - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.flush()


def _ratio(db: Session, asset: Asset, metric: str, value: float) -> None:
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric=metric,
            value=Decimal(str(value)),
            source="test",
            confidence="low",
        )
    )
    db.flush()


def test_ratio_metric_resolves_from_financial_metric(db: Session) -> None:
    asset = _asset(db, "ZZTM1")
    _ratio(db, asset, "debtToEquity", 642.52)

    assert resolve_metric_value(db, asset, "debt_to_equity") == 642.52


def test_ratio_metric_is_none_when_not_stored(db: Session) -> None:
    asset = _asset(db, "ZZTM2")

    assert resolve_metric_value(db, asset, "trailing_pe") is None


def test_technical_snapshot_metric_resolves(db: Session) -> None:
    asset = _asset(db, "ZZTM3")
    _add_bars(db, asset, [100.0] * 20 + [70.0])  # a real decline, real RSI

    value = resolve_metric_value(db, asset, "rsi14")

    assert value is not None
    assert 0 <= value <= 100


def test_close_metric_is_the_latest_bar(db: Session) -> None:
    asset = _asset(db, "ZZTM4")
    _add_bars(db, asset, [100.0, 105.0, 110.0])

    assert resolve_metric_value(db, asset, "close") == 110.0


def test_dma200_gap_pct_is_none_without_200_sessions_of_history(db: Session) -> None:
    """The exact bug this registry has to avoid: compute_technicals's DMA200
    needs ~200 trading sessions before it's anything but None, so a short
    history must resolve to "cannot evaluate," not a fabricated number."""
    asset = _asset(db, "ZZTM5")
    _add_bars(db, asset, [100.0] * 30)

    assert resolve_metric_value(db, asset, "dma200_gap_pct") is None


def test_dma20_gap_pct_matches_the_below_dma_screen_formula(db: Session) -> None:
    # 19 flat bars at 100, then a drop to 80 — dma20 over the last 20
    # closes is (19*100 + 80) / 20 = 99.0, and gap = (80 - 99) / 99 * 100.
    asset = _asset(db, "ZZTM6")
    _add_bars(db, asset, [100.0] * 19 + [80.0])

    value = resolve_metric_value(db, asset, "dma20_gap_pct")

    assert value is not None
    expected = (80.0 - 99.0) / 99.0 * 100
    assert round(value, 4) == round(expected, 4)
    assert value < 0  # price is below its DMA


def test_unknown_metric_key_returns_none(db: Session) -> None:
    asset = _asset(db, "ZZTM7")

    assert resolve_metric_value(db, asset, "not_a_real_metric") is None


def test_metric_keys_cover_the_documented_registry() -> None:
    assert "debt_to_equity" in METRIC_KEYS
    assert "dma200_gap_pct" in METRIC_KEYS
    assert "rsi14" in METRIC_KEYS
    assert len(METRIC_KEYS) >= 15
