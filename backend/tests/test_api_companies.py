import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset, Company, Industry
from app.db.session import get_db
from app.domain.models import Bar
from app.main import app
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    """Share the rollback-scoped `db` fixture's session with the app, so API
    requests run in the same transaction as test setup — nothing committed,
    nothing left behind in the dev database."""

    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _stub_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every API test in this file must be network-free and deterministic."""
    today = dt.date.today()
    bars = [
        Bar(
            date=today - dt.timedelta(days=1), open=100, high=101, low=99, close=100.0,
            volume=1000,
        ),
        Bar(date=today, open=100, high=102, low=99, close=101.5, volume=1200),
    ]
    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: bars)
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )


@pytest.fixture
def seeded_asset(db: Session) -> Asset:
    industry = Industry(code="ZZIND1", name="Test Industry")
    db.add(industry)
    db.flush()
    asset = Asset(symbol="ZZAPI1", exchange="NSE", market="IN", name="Test API Co")
    db.add(asset)
    db.flush()
    db.add(Company(asset_id=asset.id, sector="Test Sector", industry_id=industry.id))
    db.flush()
    return asset


def test_search_returns_matching_assets(seeded_asset: Asset) -> None:
    response = client.get("/api/v1/assets/search", params={"q": "ZZAPI1"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "db"
    assert any(item["symbol"] == "ZZAPI1" for item in body["data"])


def test_search_requires_query_param() -> None:
    response = client.get("/api/v1/assets/search")
    assert response.status_code == 422


def test_get_company_returns_header_and_latest_price(seeded_asset: Asset) -> None:
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["symbol"] == "ZZAPI1"
    assert body["data"]["sector"] == "Test Sector"
    assert body["data"]["industry"] == "Test Industry"
    assert body["data"]["latest_price"]["close"] == pytest.approx(101.5)
    assert body["meta"]["confidence"] == "high"


def test_get_company_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL")
    assert response.status_code == 404


def test_get_company_symbol_lookup_is_case_insensitive(seeded_asset: Asset) -> None:
    response = client.get("/api/v1/companies/zzapi1")
    assert response.status_code == 200


def test_get_prices_returns_series(seeded_asset: Asset) -> None:
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/prices", params={"range": "1m"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["data"][-1]["close"] == pytest.approx(101.5)


def test_get_prices_rejects_unsupported_range(seeded_asset: Asset) -> None:
    response = client.get(
        f"/api/v1/companies/{seeded_asset.symbol}/prices", params={"range": "10y"}
    )
    assert response.status_code == 400


def test_get_technicals_returns_snapshot_and_series(seeded_asset: Asset) -> None:
    response = client.get(
        f"/api/v1/companies/{seeded_asset.symbol}/technicals", params={"range": "1m"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["latest"]["close"] == pytest.approx(101.5)
    # Only 2 bars seeded -> DMA20 needs 20, must gracefully be null, not fabricated.
    assert body["data"]["latest"]["dma20"] is None
    assert len(body["data"]["series"]["close"]) == 2
