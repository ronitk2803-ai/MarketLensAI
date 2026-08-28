import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV
from app.db.session import get_db
from app.main import app
from tests.helpers import auth_headers

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




def test_watchlist_requires_authentication() -> None:
    response = client.get("/api/v1/watchlist")
    assert response.status_code == 401


def test_add_requires_authentication() -> None:
    response = client.post("/api/v1/watchlist/ZZAPIWL1")
    assert response.status_code == 401


def test_remove_requires_authentication() -> None:
    response = client.delete("/api/v1/watchlist/ZZAPIWL1")
    assert response.status_code == 401


def test_watchlist_is_empty_for_a_new_account() -> None:
    headers = auth_headers("newacct")

    response = client.get("/api/v1/watchlist", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == {"quotes": [], "unknown_symbols": []}


def test_add_then_list_returns_the_quote(db: Session) -> None:
    _seed(db, "ZZAPIWL1", [100.0, 105.0, 110.0])
    headers = auth_headers("addlist")

    add = client.post("/api/v1/watchlist/ZZAPIWL1", headers=headers)
    assert add.status_code == 200

    response = client.get("/api/v1/watchlist", params={"deltas": "7"}, headers=headers)

    assert response.status_code == 200
    quotes = response.json()["data"]["quotes"]
    assert quotes[0]["symbol"] == "ZZAPIWL1"
    assert quotes[0]["close"] == 110.0


def test_add_unknown_symbol_404s(db: Session) -> None:
    headers = auth_headers("addunknown")

    response = client.post("/api/v1/watchlist/ZZDOESNOTEXIST", headers=headers)

    assert response.status_code == 404


def test_remove_takes_it_off_the_list(db: Session) -> None:
    _seed(db, "ZZAPIWL2", [100.0])
    headers = auth_headers("remove")
    client.post("/api/v1/watchlist/ZZAPIWL2", headers=headers)

    remove = client.delete("/api/v1/watchlist/ZZAPIWL2", headers=headers)
    assert remove.status_code == 200

    response = client.get("/api/v1/watchlist", headers=headers)
    assert response.json()["data"]["quotes"] == []


def test_remove_never_added_symbol_is_not_an_error(db: Session) -> None:
    _seed(db, "ZZAPIWL3", [100.0])
    headers = auth_headers("removenoop")

    response = client.delete("/api/v1/watchlist/ZZAPIWL3", headers=headers)

    assert response.status_code == 200


def test_rejects_non_integer_deltas(db: Session) -> None:
    _seed(db, "ZZAPIWL4", [100.0])
    headers = auth_headers("deltas1")
    client.post("/api/v1/watchlist/ZZAPIWL4", headers=headers)

    response = client.get(
        "/api/v1/watchlist", params={"deltas": "seven"}, headers=headers
    )
    assert response.status_code == 400


def test_rejects_zero_or_negative_delta_windows(db: Session) -> None:
    _seed(db, "ZZAPIWL5", [100.0])
    headers = auth_headers("deltas2")
    client.post("/api/v1/watchlist/ZZAPIWL5", headers=headers)

    response = client.get("/api/v1/watchlist", params={"deltas": "0"}, headers=headers)
    assert response.status_code == 400


def test_deltas_default_to_7_14_30_when_omitted(db: Session) -> None:
    _seed(db, "ZZAPIWL6", [100.0] * 40)
    headers = auth_headers("deltas3")
    client.post("/api/v1/watchlist/ZZAPIWL6", headers=headers)

    response = client.get("/api/v1/watchlist", headers=headers)

    assert response.status_code == 200
    deltas = response.json()["data"]["quotes"][0]["deltas"]
    assert set(deltas.keys()) == {"7", "14", "30"}


def test_response_includes_range_stats_and_spark(db: Session) -> None:
    _seed(db, "ZZAPIWL7", [50.0, 200.0, 30.0, 100.0])
    headers = auth_headers("rangestats")
    client.post("/api/v1/watchlist/ZZAPIWL7", headers=headers)

    response = client.get("/api/v1/watchlist", headers=headers)

    quote = response.json()["data"]["quotes"][0]
    assert quote["all_time"]["high"] == 200.0
    assert quote["all_time"]["low"] == 30.0
    assert quote["week_52"] is not None
    assert isinstance(quote["spark"], list) and len(quote["spark"]) > 0


def test_watchlists_are_isolated_per_account(db: Session) -> None:
    _seed(db, "ZZAPIWLALICE", [100.0])
    _seed(db, "ZZAPIWLBOB", [100.0])
    alice_headers = auth_headers("alice")
    bob_headers = auth_headers("bob")

    client.post("/api/v1/watchlist/ZZAPIWLALICE", headers=alice_headers)
    client.post("/api/v1/watchlist/ZZAPIWLBOB", headers=bob_headers)

    alice_quotes = client.get("/api/v1/watchlist", headers=alice_headers).json()["data"]["quotes"]
    bob_quotes = client.get("/api/v1/watchlist", headers=bob_headers).json()["data"]["quotes"]
    alice_symbols = {q["symbol"] for q in alice_quotes}
    bob_symbols = {q["symbol"] for q in bob_quotes}

    assert alice_symbols == {"ZZAPIWLALICE"}
    assert bob_symbols == {"ZZAPIWLBOB"}
