import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV
from app.domain.models import Bar
from app.providers.errors import ProviderError
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.services.prices import get_price_history


def _make_asset(db: Session, symbol: str = "ZZPRICE1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Price Co")
    db.add(asset)
    db.flush()
    return asset


def test_returns_cached_bars_without_calling_any_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=dt.date(2026, 1, 5),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=1000,
            source="nse_bhavcopy",
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider should not be called when cache already covers the range")

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", _boom)

    bars, source = get_price_history(db, asset, dt.date(2026, 1, 5), dt.date(2026, 1, 5))

    assert source == "cache"
    assert bars == [
        Bar(date=dt.date(2026, 1, 5), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)
    ]


def test_fetches_and_persists_when_range_extends_past_cached_data(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db, "ZZPRICE2")
    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=dt.date(2026, 1, 5),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=1000,
            source="nse_bhavcopy",
        )
    )
    db.flush()

    fetched_ranges = []

    def fake_get_ohlcv(self, asset_ref, start, end, interval):  # type: ignore[no-untyped-def]
        fetched_ranges.append((start, end))
        return [
            Bar(date=dt.date(2026, 1, 6), open=101, high=102, low=100, close=101.5, volume=2000)
        ]

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", fake_get_ohlcv)

    bars, source = get_price_history(db, asset, dt.date(2026, 1, 5), dt.date(2026, 1, 6))

    assert source == "nse_bhavcopy"  # Upstox has no token in tests -> falls through
    assert [b.date for b in bars] == [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    # Only the missing gap was fetched, not the whole range again.
    assert fetched_ranges == [(dt.date(2026, 1, 6), dt.date(2026, 1, 6))]

    persisted = db.query(PriceOHLCV).filter_by(asset_id=asset.id, date=dt.date(2026, 1, 6)).one()
    assert persisted.close == Decimal("101.5")
    assert persisted.source == "nse_bhavcopy"


def test_fetches_full_range_when_nothing_cached(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db, "ZZPRICE3")

    def fake_get_ohlcv(self, asset_ref, start, end, interval):  # type: ignore[no-untyped-def]
        return [Bar(date=dt.date(2026, 2, 1), open=1, high=1, low=1, close=1, volume=1)]

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", fake_get_ohlcv)

    bars, source = get_price_history(db, asset, dt.date(2026, 2, 1), dt.date(2026, 2, 1))
    assert source == "nse_bhavcopy"
    assert len(bars) == 1


def test_on_demand_fetch_is_capped_to_a_recent_window(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live request for a full year of uncached history must not trigger
    a deep backfill (NSE Bhavcopy has no multi-day-per-request endpoint —
    that would be ~365 sequential HTTP calls). Only the last
    MAX_ON_DEMAND_FETCH_DAYS are requested; the rest of the range is simply
    absent from the result, not fabricated or blocked on."""
    asset = _make_asset(db, "ZZPRICE5")
    requested_ranges = []

    def fake_get_ohlcv(self, asset_ref, start, end, interval):  # type: ignore[no-untyped-def]
        requested_ranges.append((start, end))
        return []

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", fake_get_ohlcv)

    get_price_history(db, asset, dt.date(2025, 1, 1), dt.date(2026, 1, 1))

    assert len(requested_ranges) == 1
    fetched_start, fetched_end = requested_ranges[0]
    assert fetched_end == dt.date(2026, 1, 1)
    assert (fetched_end - fetched_start).days <= 10


def test_repeated_requests_do_not_repeatedly_refetch_within_the_cooldown(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified live: without this, a weekend date range re-triggers the
    full Bhavcopy fetch loop on every single request forever, since
    "latest stored < today" stays true until the next trading session."""
    asset = _make_asset(db, "ZZPRICE6")
    call_count = 0

    def fake_get_ohlcv(self, asset_ref, start, end, interval):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return []  # e.g. a weekend: provider reachable, genuinely no new data

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", fake_get_ohlcv)

    get_price_history(db, asset, dt.date(2026, 1, 1), dt.date(2026, 1, 10))
    get_price_history(db, asset, dt.date(2026, 1, 1), dt.date(2026, 1, 10))
    get_price_history(db, asset, dt.date(2026, 1, 1), dt.date(2026, 1, 10))

    assert call_count == 1


def test_degrades_gracefully_when_every_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db, "ZZPRICE4")

    def fail(self, asset_ref, start, end, interval):  # type: ignore[no-untyped-def]
        raise ProviderError("nse_bhavcopy", "simulated outage")

    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", fail)

    bars, source = get_price_history(db, asset, dt.date(2026, 2, 1), dt.date(2026, 2, 1))

    assert bars == []
    assert source == "cache"  # nothing new was fetched; not an error
