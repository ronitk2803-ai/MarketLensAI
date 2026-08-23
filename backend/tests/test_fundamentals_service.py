import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, FinancialStatement
from app.domain.models import AssetRef, Ratios, Statements
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider
from app.services.fundamentals import get_or_fetch_ratios, get_or_fetch_statements


def _make_asset(db: Session, symbol: str = "ZZFUND1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Fundamentals Co")
    db.add(asset)
    db.flush()
    return asset


def test_get_or_fetch_ratios_fetches_and_persists_on_first_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    fake_ratios = Ratios(
        asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
        as_of=dt.date.today(),
        values={"debtToEquity": 36.65, "priceToBook": 1.97},
    )
    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", lambda *a, **k: fake_ratios)

    rows = get_or_fetch_ratios(db, asset)

    assert {r.metric: float(r.value) for r in rows} == {"debtToEquity": 36.65, "priceToBook": 1.97}
    assert all(r.confidence == "low" for r in rows)
    assert all(r.source == "yfinance_fundamentals" for r in rows)


def test_get_or_fetch_ratios_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric="beta",
            value=0.157,
            source="yfinance_fundamentals",
            confidence="low",
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not call the provider when rows are already stored")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", _boom)

    rows = get_or_fetch_ratios(db, asset)
    assert len(rows) == 1
    assert rows[0].metric == "beta"


def test_get_or_fetch_ratios_returns_empty_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", fail)

    assert get_or_fetch_ratios(db, asset) == []


def test_get_or_fetch_statements_fetches_and_persists(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    fake_statements = [
        Statements(
            asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
            period_type="FY",
            period_end=dt.date(2026, 3, 31),
            statement_type="income",
            line_items={"totalRevenue": 10572190000000.0, "netIncome": 438510000000.0},
        ),
        Statements(
            asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
            period_type="FY",
            period_end=dt.date(2025, 3, 31),
            statement_type="income",
            line_items={"totalRevenue": 5173490000000.0, "netIncome": 352620000000.0},
        ),
    ]
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider, "get_all_statements", lambda *a, **k: fake_statements
    )

    rows = get_or_fetch_statements(db, asset, "income", "FY")

    assert len(rows) == 4  # 2 periods x 2 line items each
    assert rows[0].period_end == dt.date(2026, 3, 31)  # most recent first
    assert {r.line_item for r in rows if r.period_end == dt.date(2026, 3, 31)} == {
        "totalRevenue",
        "netIncome",
    }


def test_get_or_fetch_statements_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    db.add(
        FinancialStatement(
            asset_id=asset.id,
            period_type="FY",
            period_end=dt.date(2026, 3, 31),
            statement_type="income",
            line_item="netIncome",
            value=438510000000,
            source="yfinance_fundamentals",
            confidence="low",
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not call the provider when rows are already stored")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", _boom)

    rows = get_or_fetch_statements(db, asset, "income", "FY")
    assert len(rows) == 1


def test_get_or_fetch_statements_returns_empty_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", fail)

    assert get_or_fetch_statements(db, asset) == []
