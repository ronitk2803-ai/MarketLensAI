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


def _seed_falling_asset(db: Session, symbol: str) -> None:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    today = dt.date.today()
    closes = [100.0] * 25 + [60.0]
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
    db.flush()


def _simple_tree() -> dict:
    return {"op": "and", "children": [{"metric": "change_5d_pct", "operator": "lt",
                                       "threshold": -10}]}


def test_metrics_endpoint_is_public_and_lists_the_vocabulary() -> None:
    response = client.get("/api/v1/screener/metrics")
    assert response.status_code == 200
    body = response.json()
    keys = {m["key"] for m in body["data"]}
    assert {"close", "rsi14", "dma200_gap_pct", "debt_to_equity"} <= keys
    # `unit` is what lets the UI say whether 15 means 15% or 1500%.
    by_key = {m["key"]: m for m in body["data"]}
    assert by_key["debt_to_equity"]["unit"] == "percent"
    assert by_key["revenue_growth"]["unit"] == "fraction"


def test_run_requires_authentication() -> None:
    response = client.post("/api/v1/screener/run", json={"tree": _simple_tree()})
    assert response.status_code == 401


def test_run_returns_matching_hits(db: Session) -> None:
    _seed_falling_asset(db, "ZZAPISC1")
    headers = auth_headers("screener1")

    response = client.post(
        "/api/v1/screener/run", json={"tree": _simple_tree()}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    symbols = {row["symbol"] for row in body["data"]}
    assert "ZZAPISC1" in symbols
    assert body["meta"]["universe_size"] > 0
    assert any(c["metric"] == "change_5d_pct" for c in body["meta"]["coverage"])


def test_run_rejects_an_unknown_metric(db: Session) -> None:
    headers = auth_headers("screener2")
    tree = {"op": "and", "children": [{"metric": "not_a_metric", "operator": "lt",
                                       "threshold": 1}]}

    response = client.post("/api/v1/screener/run", json={"tree": tree}, headers=headers)

    assert response.status_code == 400
    assert "not_a_metric" in response.json()["detail"]


def test_run_rejects_an_unknown_industry(db: Session) -> None:
    headers = auth_headers("screener3")

    response = client.post(
        "/api/v1/screener/run",
        json={"tree": _simple_tree(), "industry": "not-an-industry"},
        headers=headers,
    )

    assert response.status_code == 400


def test_run_rejects_an_empty_group(db: Session) -> None:
    """An empty AND is vacuously true and would return the whole universe."""
    headers = auth_headers("screener4")

    response = client.post(
        "/api/v1/screener/run", json={"tree": {"op": "and", "children": []}}, headers=headers
    )

    assert response.status_code == 422


def test_run_rejects_an_over_nested_tree(db: Session) -> None:
    headers = auth_headers("screener5")
    tree: dict = {"metric": "close", "operator": "lt", "threshold": 1}
    for _ in range(6):
        tree = {"op": "and", "children": [tree]}

    response = client.post("/api/v1/screener/run", json={"tree": tree}, headers=headers)

    assert response.status_code == 422


def test_run_rejects_too_many_conditions(db: Session) -> None:
    headers = auth_headers("screener6")
    tree = {
        "op": "and",
        "children": [
            {
                "op": "or",
                "children": [
                    {"metric": "close", "operator": "lt", "threshold": float(i)}
                    for i in range(10)
                ],
            }
            for _ in range(3)
        ],
    }

    response = client.post("/api/v1/screener/run", json={"tree": tree}, headers=headers)

    assert response.status_code == 422


def test_run_rejects_the_eq_operator(db: Session) -> None:
    """Exact float equality against a computed indicator can never match,
    so offering it would only produce unexplainable empty results."""
    headers = auth_headers("screener7")
    tree = {"op": "and", "children": [{"metric": "rsi14", "operator": "eq", "threshold": 30}]}

    response = client.post("/api/v1/screener/run", json={"tree": tree}, headers=headers)

    assert response.status_code == 422
