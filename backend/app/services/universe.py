"""Seeds `asset`/`instrument_map` from a provider's instrument list, and
resolves an `AssetRef` back to a provider-specific instrument key.

Kept in services (not providers) because it owns the DB transaction and
upsert policy — providers stay DB-oblivious and receive a resolver callable
instead (see app/providers/india/upstox.py).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset, InstrumentMap
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.upstox import UpstoxInstrument


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: int
    updated: int
    total: int


def seed_assets_from_upstox_instruments(
    db: Session, instruments: list[UpstoxInstrument]
) -> SeedResult:
    created = 0
    updated = 0
    for instrument in instruments:
        asset = (
            db.query(Asset)
            .filter_by(market="IN", exchange=instrument.exchange, symbol=instrument.trading_symbol)
            .one_or_none()
        )
        if asset is None:
            asset = Asset(
                symbol=instrument.trading_symbol,
                exchange=instrument.exchange,
                market="IN",
                name=instrument.name,
                isin=instrument.isin,
            )
            db.add(asset)
            db.flush()
            created += 1
        else:
            asset.name = instrument.name
            asset.isin = instrument.isin
            updated += 1

        mapping = (
            db.query(InstrumentMap)
            .filter_by(provider="upstox", provider_instrument_key=instrument.instrument_key)
            .one_or_none()
        )
        if mapping is None:
            db.add(
                InstrumentMap(
                    asset_id=asset.id,
                    provider="upstox",
                    provider_instrument_key=instrument.instrument_key,
                )
            )
        else:
            mapping.asset_id = asset.id

    db.flush()
    return SeedResult(created=created, updated=updated, total=len(instruments))


def resolve_upstox_instrument_key(db: Session, asset: AssetRef) -> str:
    row = (
        db.query(InstrumentMap)
        .join(Asset, Asset.id == InstrumentMap.asset_id)
        .filter(
            InstrumentMap.provider == "upstox",
            Asset.market == asset.market,
            Asset.exchange == asset.exchange,
            Asset.symbol == asset.symbol,
        )
        .one_or_none()
    )
    if row is None:
        raise ProviderError(
            "upstox", f"no instrument_key mapped for {asset.exchange}:{asset.symbol}"
        )
    return row.provider_instrument_key
