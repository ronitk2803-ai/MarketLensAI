import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, Company, Industry, InstrumentMap
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.nse_indices import IndexConstituent
from app.providers.india.upstox import UpstoxInstrument
from app.services.universe import (
    SeedResult,
    classify_asset_class,
    filter_to_index,
    industry_code,
    reconcile_active_universe,
    resolve_upstox_instrument_key,
    seed_assets_from_upstox_instruments,
    sync_company_industries,
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


def _constituent(symbol: str, isin: str | None) -> IndexConstituent:
    return IndexConstituent(
        symbol=symbol, name=f"{symbol} Ltd.", industry="Test", isin=isin, series="EQ"
    )


def test_filter_to_index_matches_on_isin() -> None:
    members = [_constituent("RENAMED", "INE002A01018")]

    scoped = filter_to_index(INSTRUMENTS, members)

    # ISIN wins over symbol: the constituent list has since renamed the
    # ticker but it is the same instrument, and dropping it would silently
    # shrink the universe on every rename.
    assert [i.trading_symbol for i in scoped] == ["ZZTEST1"]


def test_filter_to_index_falls_back_to_symbol_when_isin_is_blank() -> None:
    members = [_constituent("ZZTEST2", None)]

    scoped = filter_to_index(INSTRUMENTS, members)

    assert [i.trading_symbol for i in scoped] == ["ZZTEST2"]


def test_filter_to_index_excludes_instruments_outside_the_index() -> None:
    members = [_constituent("ZZTEST1", "INE002A01018")]

    scoped = filter_to_index(INSTRUMENTS, members)

    assert len(scoped) == 1
    assert scoped[0].trading_symbol == "ZZTEST1"


def test_reconcile_deactivates_assets_that_left_the_index(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)

    # Only the first is still a member.
    result = reconcile_active_universe(db, [_constituent("ZZTEST1", "INE002A01018")])

    kept = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST1").one()
    dropped = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST2").one()
    assert kept.active is True
    assert dropped.active is False
    assert result.deactivated >= 1


def test_reconcile_reactivates_a_returning_constituent(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    asset = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST2").one()
    asset.active = False
    db.flush()

    result = reconcile_active_universe(
        db,
        [_constituent("ZZTEST1", "INE002A01018"), _constituent("ZZTEST2", "INE467B01029")],
    )

    db.refresh(asset)
    assert asset.active is True
    assert result.reactivated >= 1


def test_reconcile_preserves_the_deactivated_assets_row(db: Session) -> None:
    # Deactivation must never delete: price history and stored scores have
    # to survive a rebalance so the stock can come back cheaply.
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    before = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST2").one().id

    reconcile_active_universe(db, [_constituent("ZZTEST1", "INE002A01018")])

    still_there = db.query(Asset).filter_by(id=before).one_or_none()
    assert still_there is not None


def _constituent_with_industry(symbol: str, isin: str | None, industry: str) -> IndexConstituent:
    return IndexConstituent(
        symbol=symbol, name=f"{symbol} Ltd.", industry=industry, isin=isin, series="EQ"
    )


def test_industry_code_slugifies_nse_names() -> None:
    assert industry_code("Financial Services") == "financial-services"
    assert industry_code("Oil Gas & Consumable Fuels") == "oil-gas-consumable-fuels"
    assert industry_code("Metals & Mining") == "metals-mining"


def test_sync_creates_industries_and_links_companies(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    members = [
        _constituent_with_industry("ZZTEST1", "INE002A01018", "Financial Services"),
        _constituent_with_industry("ZZTEST2", "INE467B01029", "Information Technology"),
    ]

    result = sync_company_industries(db, members)

    assert result.companies_linked == 2
    asset = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST1").one()
    company = db.query(Company).filter_by(asset_id=asset.id).one()
    assert company.industry is not None
    assert company.industry.name == "Financial Services"
    assert company.industry.code == "financial-services"


def test_sync_assigns_score_profile_keys_from_the_industry_map(db: Session) -> None:
    """sync_company_industries is the only thing that ever writes Industry
    rows, so it's the only place score_profile_key can be kept correct."""
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    members = [
        _constituent_with_industry("ZZTEST1", "INE002A01018", "Financial Services"),
        _constituent_with_industry("ZZTEST2", "INE467B01029", "Information Technology"),
    ]

    sync_company_industries(db, members)

    financials = db.query(Industry).filter_by(code="financial-services").one()
    assert financials.score_profile_key == "financials"
    # Unmapped industries stay on default — profiles are seeded only where
    # a component is structurally invalid, not for every sector.
    it = db.query(Industry).filter_by(code="information-technology").one()
    assert it.score_profile_key == "default"


def test_sync_reapplies_score_profile_key_to_an_existing_industry(db: Session) -> None:
    """A reseed must not leave score_profile_key frozen at whatever it was
    when the row was first created — otherwise adding an industry to the
    map would silently never take effect."""
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    members = [_constituent_with_industry("ZZTEST1", "INE002A01018", "Financial Services")]
    sync_company_industries(db, members)

    industry = db.query(Industry).filter_by(code="financial-services").one()
    industry.score_profile_key = "default"  # simulate a row seeded before the map existed
    db.flush()

    sync_company_industries(db, members)

    db.refresh(industry)
    assert industry.score_profile_key == "financials"


def test_sync_reuses_an_existing_industry_row(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    members = [
        _constituent_with_industry("ZZTEST1", "INE002A01018", "Financial Services"),
        _constituent_with_industry("ZZTEST2", "INE467B01029", "Financial Services"),
    ]

    sync_company_industries(db, members)
    before = db.query(Industry).filter_by(code="financial-services").count()
    # Re-running the monthly seed must not duplicate the taxonomy.
    sync_company_industries(db, members)

    assert before == 1
    assert db.query(Industry).filter_by(code="financial-services").count() == 1


def test_sync_moves_a_company_that_was_reclassified(db: Session) -> None:
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    asset = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST1").one()

    sync_company_industries(
        db, [_constituent_with_industry("ZZTEST1", "INE002A01018", "Services")]
    )
    sync_company_industries(
        db, [_constituent_with_industry("ZZTEST1", "INE002A01018", "Capital Goods")]
    )

    company = db.query(Company).filter_by(asset_id=asset.id).one()
    assert company.industry is not None
    assert company.industry.name == "Capital Goods"


def test_sync_leaves_sector_null_rather_than_duplicating_industry(db: Session) -> None:
    # NSE gives one classification level; writing it into both fields would
    # invent a distinction the source does not make.
    seed_assets_from_upstox_instruments(db, INSTRUMENTS)
    asset = db.query(Asset).filter_by(market="IN", exchange="NSE", symbol="ZZTEST1").one()

    sync_company_industries(
        db, [_constituent_with_industry("ZZTEST1", "INE002A01018", "Healthcare")]
    )

    company = db.query(Company).filter_by(asset_id=asset.id).one()
    assert company.sector is None
    assert company.industry is not None and company.industry.name == "Healthcare"


def test_sync_ignores_constituents_with_no_matching_asset(db: Session) -> None:
    result = sync_company_industries(
        db, [_constituent_with_industry("ZZNOSUCHASSET", "INE999Z01099", "Power")]
    )

    assert result.companies_linked == 0
