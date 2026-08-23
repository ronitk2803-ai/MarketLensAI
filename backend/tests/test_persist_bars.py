import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV
from app.domain.models import Bar
from app.services.prices import persist_bars


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Persist Co")
    db.add(asset)
    db.flush()
    return asset


def _bar(day: dt.date, close: float) -> Bar:
    return Bar(date=day, open=close, high=close, low=close, close=close, volume=100)


def test_persist_bars_inserts_new_rows(db: Session) -> None:
    asset = _asset(db, "ZZPERSIST1")
    day = dt.date(2026, 1, 5)

    persist_bars(db, asset.id, [_bar(day, 100.0), _bar(day + dt.timedelta(days=1), 101.0)], "src")

    rows = db.query(PriceOHLCV).filter_by(asset_id=asset.id).order_by(PriceOHLCV.date).all()
    assert [float(r.close) for r in rows] == [100.0, 101.0]


def test_persist_bars_updates_an_existing_date_rather_than_duplicating(db: Session) -> None:
    asset = _asset(db, "ZZPERSIST2")
    day = dt.date(2026, 1, 5)

    persist_bars(db, asset.id, [_bar(day, 100.0)], "src")
    persist_bars(db, asset.id, [_bar(day, 123.5)], "src2")

    rows = db.query(PriceOHLCV).filter_by(asset_id=asset.id).all()
    assert len(rows) == 1
    assert float(rows[0].close) == 123.5
    assert rows[0].source == "src2"


def test_persist_bars_handles_a_repeated_date_within_one_batch(db: Session) -> None:
    # The pre-optimisation code re-queried per bar and so picked up the
    # just-added pending row via autoflush; the batched version has to keep
    # its own map authoritative to avoid inserting a duplicate here.
    asset = _asset(db, "ZZPERSIST3")
    day = dt.date(2026, 1, 5)

    persist_bars(db, asset.id, [_bar(day, 100.0), _bar(day, 200.0)], "src")

    rows = db.query(PriceOHLCV).filter_by(asset_id=asset.id).all()
    assert len(rows) == 1
    assert float(rows[0].close) == 200.0


def test_persist_bars_only_touches_the_given_asset(db: Session) -> None:
    a = _asset(db, "ZZPERSIST4")
    b = _asset(db, "ZZPERSIST5")
    day = dt.date(2026, 1, 5)

    persist_bars(db, a.id, [_bar(day, 100.0)], "src")
    persist_bars(db, b.id, [_bar(day, 999.0)], "src")

    assert float(db.query(PriceOHLCV).filter_by(asset_id=a.id).one().close) == 100.0
    assert float(db.query(PriceOHLCV).filter_by(asset_id=b.id).one().close) == 999.0


def test_persist_bars_with_no_bars_is_a_noop(db: Session) -> None:
    asset = _asset(db, "ZZPERSIST6")
    persist_bars(db, asset.id, [], "src")
    assert db.query(PriceOHLCV).filter_by(asset_id=asset.id).count() == 0
