import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset, Company, Industry
from app.db.session import get_db
from app.domain.models import AssetRef, Bar, Ratios
from app.main import app
from app.providers.india.google_news import GoogleNewsProvider
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider

client = TestClient(app)


def _empty_ratios() -> Ratios:
    return Ratios(asset=AssetRef(symbol="X", exchange="NSE"), as_of=dt.date.today(), values={})


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
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider, "get_ratios", lambda *a, **k: _empty_ratios()
    )
    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", lambda *a, **k: [])
    monkeypatch.setattr(GoogleNewsProvider, "get_news", lambda *a, **k: [])


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
    # 100.0 -> 101.5 is a +1.5% day change.
    assert body["data"]["latest_price"]["change_pct"] == pytest.approx(1.5)
    assert body["meta"]["confidence"] == "high"


def test_get_company_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL")
    assert response.status_code == 404


def test_get_company_symbol_lookup_is_case_insensitive(seeded_asset: Asset) -> None:
    response = client.get("/api/v1/companies/zzapi1")
    assert response.status_code == 200


def test_get_prices_returns_full_ohlc_series(seeded_asset: Asset) -> None:
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/prices", params={"range": "1m"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    latest = body["data"][-1]
    assert latest["close"] == pytest.approx(101.5)
    assert latest["open"] == pytest.approx(100)
    assert latest["high"] == pytest.approx(102)
    assert latest["low"] == pytest.approx(99)
    assert latest["volume"] == 1200


def test_get_prices_rejects_unsupported_range(seeded_asset: Asset) -> None:
    response = client.get(
        f"/api/v1/companies/{seeded_asset.symbol}/prices", params={"range": "10y"}
    )
    assert response.status_code == 400


def test_get_corporate_actions_returns_stubbed_empty_list(seeded_asset: Asset) -> None:
    # _stub_external_calls stubs YFinanceCorporateActionsProvider to return [].
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/corporate-actions")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["confidence"] == "low"


def test_get_corporate_actions_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL/corporate-actions")
    assert response.status_code == 404


def test_get_corporate_actions_maps_fields(
    seeded_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.models import CorporateActionEvent

    monkeypatch.setattr(
        YFinanceCorporateActionsProvider,
        "get_corporate_actions",
        lambda *a, **k: [
            CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0)
        ],
    )

    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/corporate-actions")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == [
        {"ex_date": "2024-10-28", "type": "split", "ratio": 2.0, "amount": None}
    ]
    assert body["meta"]["confidence"] == "high"


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


def test_get_fundamentals_returns_ratios_and_statements(
    seeded_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.models import Statements

    monkeypatch.setattr(
        YFinanceFundamentalDataProvider,
        "get_ratios",
        lambda *a, **k: Ratios(
            asset=AssetRef(symbol="ZZAPI1", exchange="NSE"),
            as_of=dt.date.today(),
            values={"debtToEquity": 36.65},
        ),
    )
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider,
        "get_all_statements",
        lambda *a, **k: [
            Statements(
                asset=AssetRef(symbol="ZZAPI1", exchange="NSE"),
                period_type="FY",
                period_end=dt.date(2026, 3, 31),
                statement_type="income",
                line_items={"totalRevenue": 100.0, "netIncome": 10.0},
            )
        ],
    )

    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/fundamentals")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["ratios"] == [
        {
            "metric": "debtToEquity",
            "value": 36.65,
            "source": "yfinance_fundamentals",
            "confidence": "low",
        }
    ]
    assert body["data"]["income_statement"][0]["line_items"] == {
        "totalRevenue": 100.0,
        "netIncome": 10.0,
    }
    assert body["meta"]["confidence"] == "low"


def test_get_fundamentals_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL/fundamentals")
    assert response.status_code == 404


def test_get_news_returns_articles(seeded_asset: Asset, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.models import Article

    monkeypatch.setattr(
        GoogleNewsProvider,
        "get_news",
        lambda *a, **k: [
            Article(
                url="https://example.com/story",
                source="Test Source",
                published_at=dt.datetime.now(dt.UTC),
                title="Test Story",
                dedup_hash="hash-1",
            )
        ],
    )

    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/news")
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["title"] == "Test Story"
    assert body["meta"]["confidence"] == "high"


def test_get_news_empty_when_none_found(seeded_asset: Asset) -> None:
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/news")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["confidence"] == "low"


def test_get_news_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL/news")
    assert response.status_code == 404


def test_get_score_returns_value_and_components(seeded_asset: Asset) -> None:
    response = client.get(f"/api/v1/companies/{seeded_asset.symbol}/score")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["value"] is not None
    assert 0 <= body["data"]["value"] <= 100
    assert len(body["data"]["components"]) == 5
    assert body["meta"]["source"] == "mlai_scoring_v1"


def test_get_score_404_for_unknown_symbol() -> None:
    response = client.get("/api/v1/companies/NOSUCHSYMBOL/score")
    assert response.status_code == 404


def test_get_score_is_cached_within_the_same_day(seeded_asset: Asset) -> None:
    first = client.get(f"/api/v1/companies/{seeded_asset.symbol}/score").json()
    second = client.get(f"/api/v1/companies/{seeded_asset.symbol}/score").json()
    assert first["data"]["as_of"] == second["data"]["as_of"]
