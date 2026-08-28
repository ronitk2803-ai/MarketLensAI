from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset
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


def _seed_asset(db: Session, symbol: str) -> None:
    db.add(Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd."))
    db.flush()




def _create_payload(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "title": "Ola's battery arm is the real long-term value",
        "body": "Because reasons.",
        "stance": "bull",
        "conviction": 4,
        "triggers": [
            {"metric": "debt_to_equity", "operator": "gt", "threshold": 1.5}
        ],
    }


def test_create_requires_authentication(db: Session) -> None:
    _seed_asset(db, "ZZAPITH1")
    response = client.post("/api/v1/theses", json=_create_payload("ZZAPITH1"))
    assert response.status_code == 401


def test_list_requires_authentication() -> None:
    assert client.get("/api/v1/theses").status_code == 401


def test_create_and_get_round_trip(db: Session) -> None:
    _seed_asset(db, "ZZAPITH2")
    headers = auth_headers("create")

    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH2"), headers=headers
    )
    assert created.status_code == 200
    body = created.json()
    assert body["symbol"] == "ZZAPITH2"
    assert body["status"] == "active"
    assert len(body["triggers"]) == 1

    fetched = client.get(f"/api/v1/theses/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["title"] == body["title"]
    assert fetched_body["events"] == []  # nothing has fired yet


def test_create_rejects_unknown_symbol(db: Session) -> None:
    headers = auth_headers("unknownsym")

    response = client.post(
        "/api/v1/theses", json=_create_payload("ZZDOESNOTEXIST"), headers=headers
    )

    assert response.status_code == 404


def test_create_rejects_unknown_metric(db: Session) -> None:
    _seed_asset(db, "ZZAPITH3")
    headers = auth_headers("unknownmetric")
    payload = _create_payload("ZZAPITH3")
    payload["triggers"] = [{"metric": "not_a_real_metric", "operator": "gt", "threshold": 1.0}]

    response = client.post("/api/v1/theses", json=payload, headers=headers)

    assert response.status_code == 400


def test_create_rejects_conviction_out_of_range(db: Session) -> None:
    _seed_asset(db, "ZZAPITH4")
    headers = auth_headers("badconviction")
    payload = _create_payload("ZZAPITH4")
    payload["conviction"] = 6

    response = client.post("/api/v1/theses", json=payload, headers=headers)

    assert response.status_code == 422


def test_create_requires_at_least_one_trigger(db: Session) -> None:
    _seed_asset(db, "ZZAPITH5")
    headers = auth_headers("notriggers")
    payload = _create_payload("ZZAPITH5")
    payload["triggers"] = []

    response = client.post("/api/v1/theses", json=payload, headers=headers)

    assert response.status_code == 422


def test_list_returns_only_the_caller_s_theses(db: Session) -> None:
    _seed_asset(db, "ZZAPITH6")
    alice_headers = auth_headers("alice")
    bob_headers = auth_headers("bob")
    client.post("/api/v1/theses", json=_create_payload("ZZAPITH6"), headers=alice_headers)

    alice_list = client.get("/api/v1/theses", headers=alice_headers).json()
    bob_list = client.get("/api/v1/theses", headers=bob_headers).json()

    assert len(alice_list) == 1
    assert bob_list == []


def test_get_another_user_s_thesis_404s_not_leaks(db: Session) -> None:
    _seed_asset(db, "ZZAPITH7")
    alice_headers = auth_headers("alice2")
    bob_headers = auth_headers("bob2")
    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH7"), headers=alice_headers
    ).json()

    response = client.get(f"/api/v1/theses/{created['id']}", headers=bob_headers)

    assert response.status_code == 404


def test_update_changes_status(db: Session) -> None:
    _seed_asset(db, "ZZAPITH8")
    headers = auth_headers("update")
    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH8"), headers=headers
    ).json()

    response = client.put(
        f"/api/v1/theses/{created['id']}", json={"status": "invalidated"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "invalidated"


def test_update_another_user_s_thesis_404s(db: Session) -> None:
    _seed_asset(db, "ZZAPITH9")
    alice_headers = auth_headers("alice3")
    bob_headers = auth_headers("bob3")
    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH9"), headers=alice_headers
    ).json()

    response = client.put(
        f"/api/v1/theses/{created['id']}", json={"status": "closed"}, headers=bob_headers
    )

    assert response.status_code == 404


def test_delete_removes_the_thesis(db: Session) -> None:
    _seed_asset(db, "ZZAPITH10")
    headers = auth_headers("delete")
    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH10"), headers=headers
    ).json()

    response = client.delete(f"/api/v1/theses/{created['id']}", headers=headers)
    assert response.status_code == 200

    assert client.get(f"/api/v1/theses/{created['id']}", headers=headers).status_code == 404


def test_delete_another_user_s_thesis_404s(db: Session) -> None:
    _seed_asset(db, "ZZAPITH11")
    alice_headers = auth_headers("alice4")
    bob_headers = auth_headers("bob4")
    created = client.post(
        "/api/v1/theses", json=_create_payload("ZZAPITH11"), headers=alice_headers
    ).json()

    response = client.delete(f"/api/v1/theses/{created['id']}", headers=bob_headers)

    assert response.status_code == 404
