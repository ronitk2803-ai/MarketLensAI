import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV, Score, ScoreProfile
from app.db.session import get_db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_list_screens_returns_all_registered_screens() -> None:
    response = client.get("/api/v1/opportunities/screens")
    assert response.status_code == 200
    body = response.json()
    ids = {s["id"] for s in body["data"]}
    assert "down_30d" in ids
    assert "below_dma50" in ids
    assert "unusual_volume" in ids


def test_get_opportunities_rejects_unknown_screen() -> None:
    response = client.get("/api/v1/opportunities", params={"screen": "not_a_screen"})
    assert response.status_code == 400


def test_get_opportunities_requires_screen_param() -> None:
    response = client.get("/api/v1/opportunities")
    assert response.status_code == 422


def test_get_opportunities_returns_matching_hits(db: Session) -> None:
    down = Asset(symbol="ZZAPIOPP1", exchange="NSE", market="IN", name="Down Co")
    db.add(down)
    db.flush()
    today = dt.date.today()
    closes = [100.0] * 10 + [70.0]
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=down.id,
                date=today - dt.timedelta(days=len(closes) - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.flush()

    response = client.get("/api/v1/opportunities", params={"screen": "down_10d"})

    assert response.status_code == 200
    body = response.json()
    symbols = {h["symbol"] for h in body["data"]}
    assert "ZZAPIOPP1" in symbols
    hit = next(h for h in body["data"] if h["symbol"] == "ZZAPIOPP1")
    assert hit["metrics"]["change_pct"] == pytest.approx(-30.0)
    assert hit["rank"] >= 1
    assert hit["opportunity_score"] is None  # no Score row exists for it yet
    assert body["meta"]["confidence"] == "high"


def test_get_opportunities_ranks_by_opportunity_score(db: Session) -> None:
    """The founder_vision.md scenario, through the full HTTP endpoint."""

    def _seed_stock(symbol: str, decline_close: float, score_value: float) -> None:
        asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=symbol)
        db.add(asset)
        db.flush()
        today = dt.date.today()
        closes = [100.0] * 10 + [decline_close]
        for i, close in enumerate(closes):
            db.add(
                PriceOHLCV(
                    asset_id=asset.id,
                    date=today - dt.timedelta(days=len(closes) - 1 - i),
                    open=Decimal(str(close)),
                    high=Decimal(str(close)),
                    low=Decimal(str(close)),
                    close=Decimal(str(close)),
                    volume=1000,
                    source="test",
                )
            )
        profile = db.query(ScoreProfile).filter_by(industry_code="default").first()
        if profile is None:
            profile = ScoreProfile(industry_code="default", version=1, weights={"x": 1.0})
            db.add(profile)
            db.flush()
        db.add(
            Score(
                asset_id=asset.id,
                profile_id=profile.id,
                value=Decimal(str(score_value)),
                coverage=Decimal("1.0"),
                confidence="high",
            )
        )
        db.flush()

    _seed_stock("ZZAPIRANKA", 70.0, 25.0)  # -30%, weak fundamentals
    _seed_stock("ZZAPIRANKB", 78.0, 75.0)  # -22%, stable fundamentals

    response = client.get("/api/v1/opportunities", params={"screen": "down_10d"})

    assert response.status_code == 200
    body = response.json()
    symbols = [h["symbol"] for h in body["data"]]
    assert symbols.index("ZZAPIRANKB") < symbols.index("ZZAPIRANKA")
