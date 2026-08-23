import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, InstrumentMap
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.upstox import UpstoxInstrument
from app.services.universe import (
    SeedResult,
    resolve_upstox_instrument_key,
    seed_assets_from_upstox_instruments,
)

INSTRUMENTS = [
    UpstoxInstrument(
        instrument_key="NSE_EQ|INE002A01018",
        trading_symbol="RELIANCE",
        name="Reliance Industries Ltd",
        isin="INE002A01018",
        exchange="NSE",
    ),
    UpstoxInstrument(
        instrument_key="NSE_EQ|INE467B01029",
        trading_symbol="TCS",
        name="Tata Consultancy Services Ltd",
        isin="INE467B01029",
        exchange="NSE",
    ),
]


def test_seed_creates_assets_and_instrument_maps(db: Session) -> None:
    result = seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    assert result == SeedResult(created=2, updated=0, total=2)
    assets = db.query(Asset).filter(Asset.symbol.in_(["RELIANCE", "TCS"])).all()
    assert {a.symbol for a in assets} == {"RELIANCE", "TCS"}
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
    assets = db.query(Asset).filter(Asset.symbol.in_(["RELIANCE", "TCS"])).all()
    assert len(assets) == 2


def test_resolve_upstox_instrument_key_after_seeding(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    key = resolve_upstox_instrument_key(
        db, AssetRef(symbol="RELIANCE", exchange="NSE", market="IN")
    )

    assert key == "NSE_EQ|INE002A01018"


def test_resolve_upstox_instrument_key_raises_when_unmapped(db: Session) -> None:
    with pytest.raises(ProviderError):
        resolve_upstox_instrument_key(db, AssetRef(symbol="UNKNOWN", exchange="NSE", market="IN"))
