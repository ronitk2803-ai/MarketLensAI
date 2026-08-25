import datetime as dt
import random
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, PriceOHLCV
from app.services.metric_registry import METRIC_KEYS, REGISTRY, resolve_metric_value
from app.services.opportunities import calendar_lookback_for, load_universe_bars_with_ids
from app.services.screener import required_lookback_days, resolve_metric_columns


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


def test_metric_keys_is_exactly_the_registry() -> None:
    """METRIC_KEYS is the thesis API's validation gate. A key present in
    one but not the other means either a metric that can't be validated,
    or a trigger a user can create that silently never fires."""
    assert set(REGISTRY) == set(METRIC_KEYS)


def test_every_metric_has_both_resolvers() -> None:
    for key, spec in REGISTRY.items():
        assert callable(spec.resolve_one), key
        assert callable(spec.resolve_many), key


def test_drawdown_pct_is_a_percentage_not_a_fraction(db: Session) -> None:
    """Regression: this key returned the raw fraction (-0.31) while
    scoring exposed the same name as a percent (-30.9), and the thesis
    form offered it with no unit hint — so a trigger typed as "-30" meant
    -3000%. Percent is canonical."""
    asset = _asset(db, "ZZTMDD")
    _add_bars(db, asset, [100.0] * 30 + [70.0])

    value = resolve_metric_value(db, asset, "drawdown_pct")

    assert value is not None
    assert round(value, 2) == -30.0


def test_every_metric_lookback_yields_enough_sessions() -> None:
    """The calendar->sessions conversion has to leave every metric enough
    room. The below_dma200 bug (listed in the UI, structurally unable to
    ever return a hit) was exactly this arithmetic being wrong."""
    for key, spec in REGISTRY.items():
        if spec.required_bars <= 0:
            continue
        sessions = calendar_lookback_for(spec.required_bars) * 246 / 365
        assert sessions >= spec.required_bars, key


def test_lookback_is_derived_from_the_tree_not_all_metrics() -> None:
    """The property that keeps a cheap tree cheap. Defaulting to the max
    over every known metric would silently make every query pay for
    dma200's window."""
    cheap = required_lookback_days({"close"})
    expensive = required_lookback_days({"dma200_gap_pct"})
    assert cheap < expensive


@pytest.mark.parametrize("metric", sorted(REGISTRY))
def test_batch_and_per_asset_resolvers_agree(db: Session, metric: str) -> None:
    """The test that keeps the two consumers of the registry honest. The
    screener resolves whole columns from already-loaded bars; the nightly
    thesis eval resolves one asset at a time, cache-first. They must
    return the same number for the same asset, or a trigger and a screen
    would disagree about the same stated condition."""
    spec = REGISTRY[metric]
    asset = _asset(db, "ZZPARITY")

    # Enough history for the deepest metric, with real movement so nothing
    # collapses to a degenerate constant series.
    rng = random.Random(7)
    closes = [100.0]
    for _ in range(400):
        closes.append(round(max(1.0, closes[-1] * (1 + rng.uniform(-0.03, 0.03))), 2))
    _add_bars(db, asset, closes)
    for field in ("debtToEquity", "priceToBook", "trailingPE", "forwardPE", "grossMargins",
                  "operatingMargins", "profitMargins", "revenueGrowth", "earningsGrowth",
                  "returnOnEquity", "returnOnAssets", "beta"):
        _ratio(db, asset, field, 1.25)

    universe, asset_ids = load_universe_bars_with_ids(
        db, required_lookback_days({metric}, min_bars=spec.required_bars)
    )
    ref = next(r for r in universe if r.symbol == "ZZPARITY")
    batch = resolve_metric_columns(db, {metric}, universe, asset_ids)[metric][ref]
    per_asset = resolve_metric_value(db, asset, metric)

    if batch is None or per_asset is None:
        assert batch == per_asset, metric
    else:
        assert round(batch, 6) == round(per_asset, 6), metric
