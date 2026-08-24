import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV
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


def _seed(db: Session, symbol: str, closes: list[float]) -> None:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    today = dt.date.today()
    n = len(closes)
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=today - dt.timedelta(days=n - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.flush()


def test_quotes_for_known_symbols(db: Session) -> None:
    _seed(db, "ZZAPIWL1", [100.0, 105.0, 110.0])

    response = client.get(
        "/api/v1/watchlist/quotes", params={"symbols": "ZZAPIWL1", "deltas": "7"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["quotes"][0]["symbol"] == "ZZAPIWL1"
    assert body["data"]["quotes"][0]["close"] == 110.0
    assert body["data"]["unknown_symbols"] == []


def test_unknown_symbol_reported_not_500d(db: Session) -> None:
    response = client.get(
        "/api/v1/watchlist/quotes", params={"symbols": "ZZDOESNOTEXIST", "deltas": "7"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["unknown_symbols"] == ["ZZDOESNOTEXIST"]


def test_mixed_known_and_unknown_symbols(db: Session) -> None:
    _seed(db, "ZZAPIWL2", [100.0])

    response = client.get(
        "/api/v1/watchlist/quotes",
        params={"symbols": "ZZAPIWL2,ZZGHOST", "deltas": "7"},
    )

    body = response.json()["data"]
    assert {q["symbol"] for q in body["quotes"]} == {"ZZAPIWL2"}
    assert body["unknown_symbols"] == ["ZZGHOST"]


def test_rejects_empty_symbol_list() -> None:
    response = client.get("/api/v1/watchlist/quotes", params={"symbols": ""})
    assert response.status_code == 400


def test_rejects_non_integer_deltas(db: Session) -> None:
    _seed(db, "ZZAPIWL3", [100.0])
    response = client.get(
        "/api/v1/watchlist/quotes", params={"symbols": "ZZAPIWL3", "deltas": "seven"}
    )
    assert response.status_code == 400


def test_rejects_zero_or_negative_delta_windows(db: Session) -> None:
    _seed(db, "ZZAPIWL4", [100.0])
    response = client.get(
        "/api/v1/watchlist/quotes", params={"symbols": "ZZAPIWL4", "deltas": "0"}
    )
    assert response.status_code == 400


def test_symbol_list_is_capped(db: Session) -> None:
    many = ",".join(f"ZZBOGUS{i}" for i in range(80))
    response = client.get("/api/v1/watchlist/quotes", params={"symbols": many, "deltas": "7"})

    assert response.status_code == 200
    total = len(response.json()["data"]["unknown_symbols"])
    assert total == 50  # MAX_SYMBOLS, not the 80 requested


def test_deltas_default_to_7_14_30_when_omitted(db: Session) -> None:
    _seed(db, "ZZAPIWL5", [100.0] * 40)
    response = client.get("/api/v1/watchlist/quotes", params={"symbols": "ZZAPIWL5"})

    assert response.status_code == 200
    deltas = response.json()["data"]["quotes"][0]["deltas"]
    assert set(deltas.keys()) == {"7", "14", "30"}


def test_response_includes_range_stats_and_spark(db: Session) -> None:
    _seed(db, "ZZAPIWL6", [50.0, 200.0, 30.0, 100.0])

    response = client.get(
        "/api/v1/watchlist/quotes", params={"symbols": "ZZAPIWL6", "deltas": "7"}
    )

    quote = response.json()["data"]["quotes"][0]
    assert quote["all_time"]["high"] == 200.0
    assert quote["all_time"]["low"] == 30.0
    assert quote["week_52"] is not None
    assert isinstance(quote["spark"], list) and len(quote["spark"]) > 0
