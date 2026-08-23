import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV
from app.providers.india.nse_bhavcopy import BhavcopyRow, NSEBhavcopyProvider
from app.services.backfill import backfill_universe_from_bhavcopy


class FakeBhavcopyProvider(NSEBhavcopyProvider):
    def __init__(self, day_data: dict[dt.date, list[BhavcopyRow]]) -> None:
        self._day_data = day_data

    def get_day_bars(self, date: dt.date) -> list[BhavcopyRow]:
        return self._day_data.get(date, [])


def _row(symbol: str, date: dt.date, close: float) -> BhavcopyRow:
    return BhavcopyRow(
        symbol=symbol,
        series="EQ",
        date=date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        delivery_qty=500,
        delivery_pct=50.0,
    )


def test_backfill_persists_only_matching_seeded_assets(db: Session) -> None:
    matched = Asset(symbol="ZZFILL1", exchange="NSE", market="IN", name="Matched Co")
    db.add(matched)
    db.flush()

    day1 = dt.date(2026, 1, 5)
    day2 = dt.date(2026, 1, 6)
    provider = FakeBhavcopyProvider(
        {
            day1: [_row("ZZFILL1", day1, 100.0), _row("UNMATCHED", day1, 50.0)],
            day2: [_row("ZZFILL1", day2, 105.0)],
        }
    )

    result = backfill_universe_from_bhavcopy(db, day1, day2, provider=provider)

    assert result.trading_days_found == 2
    assert result.days_checked == 2
    assert result.bars_persisted == 2  # UNMATCHED skipped, only ZZFILL1's 2 bars

    rows = db.query(PriceOHLCV).filter_by(asset_id=matched.id).order_by(PriceOHLCV.date).all()
    assert [r.close for r in rows] == [Decimal("100.0000"), Decimal("105.0000")]


def test_backfill_skips_non_trading_days_gracefully(db: Session) -> None:
    asset = Asset(symbol="ZZFILL2", exchange="NSE", market="IN", name="Weekend Co")
    db.add(asset)
    db.flush()

    trading_day = dt.date(2026, 1, 5)  # Monday
    weekend_day = dt.date(2026, 1, 4)  # Sunday: no data
    provider = FakeBhavcopyProvider({trading_day: [_row("ZZFILL2", trading_day, 100.0)]})

    result = backfill_universe_from_bhavcopy(db, weekend_day, trading_day, provider=provider)

    assert result.days_checked == 2
    assert result.trading_days_found == 1
    assert result.bars_persisted == 1


def test_backfill_is_idempotent_on_rerun(db: Session) -> None:
    asset = Asset(symbol="ZZFILL3", exchange="NSE", market="IN", name="Rerun Co")
    db.add(asset)
    db.flush()

    day = dt.date(2026, 1, 5)
    provider = FakeBhavcopyProvider({day: [_row("ZZFILL3", day, 100.0)]})

    backfill_universe_from_bhavcopy(db, day, day, provider=provider)
    backfill_universe_from_bhavcopy(db, day, day, provider=provider)

    rows = db.query(PriceOHLCV).filter_by(asset_id=asset.id).all()
    assert len(rows) == 1
