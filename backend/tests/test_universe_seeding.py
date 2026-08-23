import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, InstrumentMap
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.upstox import UpstoxInstrument
from app.services.universe import (
    SeedResult,
    classify_asset_class,
    resolve_upstox_instrument_key,
    seed_assets_from_upstox_instruments,
)

INSTRUMENTS = [
    UpstoxInstrument(
        instrument_key="NSE_EQ|INE002A01018",
        trading_symbol="ZZTEST1",
        name="Test Co 1",
        isin="INE002A01018",
        exchange="NSE",
    ),
    UpstoxInstrument(
        instrument_key="NSE_EQ|INE467B01029",
        trading_symbol="ZZTEST2",
        name="Test Co 2",
        isin="INE467B01029",
        exchange="NSE",
    ),
]


def test_seed_creates_assets_and_instrument_maps(db: Session) -> None:
    result = seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    assert result == SeedResult(created=2, updated=0, total=2)
    assets = db.query(Asset).filter(Asset.symbol.in_(["ZZTEST1", "ZZTEST2"])).all()
    assert {a.symbol for a in assets} == {"ZZTEST1", "ZZTEST2"}
    mappings = (
        db.query(InstrumentMap)
        .filter(InstrumentMap.asset_id.in_([a.id for a in assets]))
        .all()
    )
    assert {m.provider_instrument_key for m in mappings} == {
        "NSE_EQ|INE002A01018",
        "NSE_EQ|INE467B01029",
    }


def test_seed_is_idempotent_on_rerun(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    result = seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    assert result == SeedResult(created=0, updated=2, total=2)
    assets = db.query(Asset).filter(Asset.symbol.in_(["ZZTEST1", "ZZTEST2"])).all()
    assert len(assets) == 2


def test_resolve_upstox_instrument_key_after_seeding(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    key = resolve_upstox_instrument_key(
        db, AssetRef(symbol="ZZTEST1", exchange="NSE", market="IN")
    )

    assert key == "NSE_EQ|INE002A01018"


def test_resolve_upstox_instrument_key_raises_when_unmapped(db: Session) -> None:
    with pytest.raises(ProviderError):
        resolve_upstox_instrument_key(db, AssetRef(symbol="UNKNOWN", exchange="NSE", market="IN"))


def test_classify_asset_class_by_isin_prefix() -> None:
    # Real ISINs verified live: KOTAK PSU BANK (an ETF) is INF...,
    # RELIANCE (equity) is INE...
    assert classify_asset_class("INF174KA1A86") == "ETF"
    assert classify_asset_class("INE002A01018") == "EQUITY"
    assert classify_asset_class(None) == "EQUITY"


def test_seed_classifies_etf_by_isin_prefix(db: Session) -> None:
    etf_instrument = UpstoxInstrument(
        instrument_key="NSE_EQ|INF000ZZ9999",
        trading_symbol="ZZETF1",
        name="Test ETF",
        isin="INF000ZZ9999",
        exchange="NSE",
    )
    seed_assets_from_upstox_instruments(db, [*INSTRUMENTS, etf_instrument])

    equity = db.query(Asset).filter_by(symbol="ZZTEST1").one()
    etf = db.query(Asset).filter_by(symbol="ZZETF1").one()
    assert equity.asset_class == "EQUITY"
    assert etf.asset_class == "ETF"
