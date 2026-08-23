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
from app.providers.india.nse_indices import IndexConstituent
from app.providers.india.upstox import UpstoxInstrument


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: int
    updated: int
    total: int


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    deactivated: int
    reactivated: int
    active_total: int


def filter_to_index(
    instruments: list[UpstoxInstrument], constituents: list[IndexConstituent]
) -> list[UpstoxInstrument]:
    """Narrow a broker scrip master down to one index's members.

    Upstox's NSE_EQ dump is the *full* tradable list (~2.6k instruments);
    the MVP universe is the Nifty 500 (Build_plan.md §Q). Seeding the whole
    dump makes the nightly job ~5x longer for stocks outside the product's
    scope, so the index CSV is what defines membership and the dump only
    supplies the instrument keys.

    Matches on ISIN first — symbols get reassigned on renames, ISINs do
    not — and falls back to symbol for any constituent whose ISIN is blank
    in the CSV.
    """
    isins = {c.isin for c in constituents if c.isin}
    symbols = {c.symbol for c in constituents}
    return [
        instrument
        for instrument in instruments
        if (instrument.isin and instrument.isin in isins) or instrument.trading_symbol in symbols
    ]


def reconcile_active_universe(
    db: Session,
    constituents: list[IndexConstituent],
    *,
    market: str = "IN",
    exchange: str = "NSE",
) -> ReconcileResult:
    """Make `active` mirror current index membership.

    Constituents change on rebalance (API_Sources.md §2), so a stock that
    leaves the index has to stop showing up in search, company pages, and
    screens — all of which filter on `active`. Deactivating rather than
    deleting keeps its price history and stored scores intact, so it costs
    nothing to bring back at the next rebalance.
    """
    isins = {c.isin for c in constituents if c.isin}
    symbols = {c.symbol for c in constituents}

    deactivated = 0
    reactivated = 0
    for asset in db.query(Asset).filter_by(market=market, exchange=exchange):
        in_index = (asset.isin is not None and asset.isin in isins) or asset.symbol in symbols
        if in_index and not asset.active:
            asset.active = True
            reactivated += 1
        elif not in_index and asset.active:
            asset.active = False
            deactivated += 1

    db.flush()
    active_total = (
        db.query(Asset).filter_by(market=market, exchange=exchange, active=True).count()
    )
    return ReconcileResult(
        deactivated=deactivated, reactivated=reactivated, active_total=active_total
    )


def classify_asset_class(isin: str | None) -> str:
    """Indian ISIN prefix convention: INE = listed equity, INF = mutual
    fund/ETF unit. Upstox's NSE_EQ|EQ segment mixes both (verified live: an
    ETF's unit consolidation isn't a "stock split" our corporate-actions
    source tracks the same way, so an unclassified ETF can look like a
    mechanical crash in price screens) — this is the reliable signal to
    tell them apart, not a name-pattern guess."""
    if isin and isin.startswith("INF"):
        return "ETF"
    return "EQUITY"


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
        asset_class = classify_asset_class(instrument.isin)
        if asset is None:
            asset = Asset(
                symbol=instrument.trading_symbol,
                exchange=instrument.exchange,
                market="IN",
                name=instrument.name,
                isin=instrument.isin,
                asset_class=asset_class,
            )
            db.add(asset)
            db.flush()
            created += 1
        else:
            asset.name = instrument.name
            asset.isin = instrument.isin
            asset.asset_class = asset_class
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


if __name__ == "__main__":
    # Monthly universe (re)seed (Build_plan.md §2 / API_Sources.md §2 —
    # rebalance cadence, deliberately not part of the daily job; see
    # app/jobs/daily_ingestion.py). Both sources here are public and
    # unauthenticated, so this needs no Upstox access token.
    #
    # The index CSV defines *membership*; the Upstox dump supplies the
    # instrument keys for those members. --index all skips the filter and
    # seeds the full tradable list, which is the old behaviour.
    import argparse
    import logging

    from app.core.logging import configure_logging
    from app.db.session import SessionLocal
    from app.providers.india.nse_indices import NSEIndexProvider
    from app.providers.india.upstox import fetch_instruments_raw, parse_equity_instruments

    parser = argparse.ArgumentParser(description="Seed the tradable universe.")
    parser.add_argument(
        "--index",
        default="nifty500",
        help="NSE index defining the universe, or 'all' for the full NSE_EQ dump.",
    )
    args = parser.parse_args()

    configure_logging()
    logger = logging.getLogger(__name__)

    session = SessionLocal()
    try:
        instruments = parse_equity_instruments(fetch_instruments_raw())
        logger.info("upstox instrument dump: %d NSE_EQ instruments", len(instruments))

        if args.index == "all":
            outcome = seed_assets_from_upstox_instruments(session, instruments)
            session.commit()
            logger.info("universe seed (unfiltered): %s", outcome)
            print(outcome)
        else:
            members = NSEIndexProvider().get_constituents(args.index)
            logger.info("%s constituents: %d", args.index, len(members))

            scoped = filter_to_index(instruments, members)
            missing = len(members) - len(scoped)
            if missing > 0:
                # Not fatal: a constituent with no tradable NSE_EQ instrument
                # in the dump simply has nothing to seed. Surfaced because a
                # large gap means the match keys have drifted, not that the
                # index shrank.
                logger.warning(
                    "%d of %d %s constituents had no matching instrument in the dump",
                    missing,
                    len(members),
                    args.index,
                )

            outcome = seed_assets_from_upstox_instruments(session, scoped)
            reconciled = reconcile_active_universe(session, members)
            session.commit()
            logger.info("universe seed (%s): %s", args.index, outcome)
            logger.info("universe reconcile: %s", reconciled)
            print(outcome, reconciled)
    finally:
        session.close()
