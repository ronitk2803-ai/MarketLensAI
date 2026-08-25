from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_STANDARD_HEADER = "Instrument,Qty.,Avg. cost"


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


def _auth_headers(email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def _add_payload(symbol: str) -> dict:
    return {"symbol": symbol, "quantity": 10, "avg_cost": 100}


def test_get_requires_authentication() -> None:
    assert client.get("/api/v1/portfolio").status_code == 401


def test_add_requires_authentication(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF1")
    response = client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF1"))
    assert response.status_code == 401


def test_add_and_list_round_trip(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF2")
    headers = _auth_headers("addlist@example.com")

    added = client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF2"), headers=headers)
    assert added.status_code == 200
    body = added.json()
    assert body["symbol"] == "ZZAPIPF2"
    assert body["source"] == "manual"
    assert body["cost_basis"] == 1000.0

    listed = client.get("/api/v1/portfolio", headers=headers)
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body["holdings"]) == 1
    assert listed_body["totals"]["cost_basis"] == 1000.0
    assert listed_body["totals"]["holdings_total"] == 1


def test_add_rejects_unknown_symbol(db: Session) -> None:
    headers = _auth_headers("unknownsym_pf@example.com")
    response = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZDOESNOTEXIST"), headers=headers
    )
    assert response.status_code == 404


def test_add_rejects_non_positive_quantity(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF3")
    headers = _auth_headers("badqty_pf@example.com")
    payload = _add_payload("ZZAPIPF3")
    payload["quantity"] = 0
    response = client.post("/api/v1/portfolio", json=payload, headers=headers)
    assert response.status_code == 422


def test_update_and_delete_are_ownership_scoped(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF4")
    alice_headers = _auth_headers("alice_pf@example.com")
    bob_headers = _auth_headers("bob_pf@example.com")
    created = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZAPIPF4"), headers=alice_headers
    ).json()

    update_response = client.put(
        f"/api/v1/portfolio/{created['id']}", json={"quantity": 5}, headers=bob_headers
    )
    delete_response = client.delete(f"/api/v1/portfolio/{created['id']}", headers=bob_headers)

    assert update_response.status_code == 404
    assert delete_response.status_code == 404


def test_delete_removes_the_holding(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF5")
    headers = _auth_headers("delete_pf@example.com")
    created = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZAPIPF5"), headers=headers
    ).json()

    response = client.delete(f"/api/v1/portfolio/{created['id']}", headers=headers)
    assert response.status_code == 200

    second_delete = client.delete(f"/api/v1/portfolio/{created['id']}", headers=headers)
    assert second_delete.status_code == 404


def test_import_requires_authentication() -> None:
    files = {"file": ("holdings.csv", _STANDARD_HEADER + "\n", "text/csv")}
    response = client.post("/api/v1/portfolio/import", files=files)
    assert response.status_code == 401


def test_import_rejects_non_csv_filename(db: Session) -> None:
    headers = _auth_headers("badext_pf@example.com")
    files = {"file": ("holdings.txt", _STANDARD_HEADER + "\nTCS,1,1\n", "text/plain")}
    response = client.post("/api/v1/portfolio/import", files=files, headers=headers)
    assert response.status_code == 400


def test_import_rejects_empty_file(db: Session) -> None:
    headers = _auth_headers("emptyfile_pf@example.com")
    files = {"file": ("holdings.csv", "", "text/csv")}
    response = client.post("/api/v1/portfolio/import", files=files, headers=headers)
    assert response.status_code == 400


def test_import_rejects_oversized_file(db: Session) -> None:
    headers = _auth_headers("oversized_pf@example.com")
    oversized = _STANDARD_HEADER + "\n" + ("A" * (6 * 1024 * 1024))
    files = {"file": ("holdings.csv", oversized, "text/csv")}
    response = client.post("/api/v1/portfolio/import", files=files, headers=headers)
    assert response.status_code == 400


def test_import_returns_mixed_summary(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF6")
    headers = _auth_headers("mixedimport_pf@example.com")
    csv_text = _STANDARD_HEADER + "\nZZAPIPF6,5,50\nZZDOESNOTEXIST,1,1\n"
    files = {"file": ("holdings.csv", csv_text, "text/csv")}

    response = client.post("/api/v1/portfolio/import", files=files, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    statuses = {row["symbol"]: row["status"] for row in body["rows"]}
    assert statuses["ZZAPIPF6"] == "imported"
    assert statuses["ZZDOESNOTEXIST"] == "skipped"


def test_import_only_touches_the_caller_s_own_holdings(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF7")
    alice_headers = _auth_headers("alice_import_pf@example.com")
    bob_headers = _auth_headers("bob_import_pf@example.com")
    client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF7"), headers=bob_headers)

    csv_text = _STANDARD_HEADER + "\nZZAPIPF7,9,99\n"
    files = {"file": ("holdings.csv", csv_text, "text/csv")}
    client.post("/api/v1/portfolio/import", files=files, headers=alice_headers)

    bob_portfolio = client.get("/api/v1/portfolio", headers=bob_headers).json()
    assert bob_portfolio["holdings"][0]["quantity"] == 10  # untouched by Alice's import
