import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, Company, CorporateAction, Industry, InstrumentMap, PriceOHLCV


def test_asset_roundtrip(db: Session) -> None:
    asset = Asset(symbol="ZZTEST1", exchange="NSE", market="IN", name="Test Co 1")
    db.add(asset)
    db.flush()

    db.add(
        InstrumentMap(
            asset_id=asset.id, provider="upstox", provider_instrument_key="NSE_EQ|INE002A01018"
        )
    )

    industry = Industry(code="OIL_GAS", name="Oil & Gas", score_profile_key="default")
    db.add(industry)
    db.flush()

    db.add(Company(asset_id=asset.id, sector="Energy", industry_id=industry.id))

    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=dt.date(2026, 8, 21),
            open=Decimal("1400.00"),
            high=Decimal("1420.50"),
            low=Decimal("1395.00"),
            close=Decimal("1410.25"),
            volume=1_000_000,
            source="upstox",
        )
    )

    db.add(
        CorporateAction(
            asset_id=asset.id,
            type="bonus",
            ex_date=dt.date(2020, 10, 14),
            ratio=Decimal("2.0"),
            source="nse",
        )
    )
    db.flush()

    fetched = db.query(Asset).filter_by(symbol="ZZTEST1", market="IN").one()
    assert fetched.name == "Test Co 1"
    assert fetched.company.sector == "Energy"
    assert fetched.company.industry.code == "OIL_GAS"
    assert len(fetched.instrument_maps) == 1

    bar = db.query(PriceOHLCV).filter_by(asset_id=asset.id, date=dt.date(2026, 8, 21)).one()
    assert bar.close == Decimal("1410.25")

    action = db.query(CorporateAction).filter_by(asset_id=asset.id).one()
    assert action.type == "bonus"
    assert action.ratio == Decimal("2.0")
