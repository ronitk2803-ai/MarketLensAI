from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.db.session import get_db
from app.main import app
from tests.helpers import auth_headers

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




def _add_payload(symbol: str) -> dict:
    return {"symbol": symbol, "quantity": 10, "avg_cost": 100}


def _import(headers: dict[str, str], csv_text: str, broker: str, filename: str = "holdings.csv"):
    files = {"file": (filename, csv_text, "text/csv")}
    return client.post(
        "/api/v1/portfolio/import", files=files, data={"broker": broker}, headers=headers
    )


def test_get_requires_authentication() -> None:
    assert client.get("/api/v1/portfolio").status_code == 401


def test_add_requires_authentication(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF1")
    response = client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF1"))
    assert response.status_code == 401


def test_add_and_list_round_trip(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF2")
    headers = auth_headers("addlist")

    added = client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF2"), headers=headers)
    assert added.status_code == 200
    body = added.json()
    assert body["symbol"] == "ZZAPIPF2"
    assert body["cost_basis"] == 1000.0
    assert len(body["lots"]) == 1
    assert body["lots"][0]["broker"] == "manual"

    listed = client.get("/api/v1/portfolio", headers=headers)
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body["holdings"]) == 1
    assert listed_body["totals"]["cost_basis"] == 1000.0
    assert listed_body["totals"]["holdings_total"] == 1


def test_add_rejects_unknown_symbol(db: Session) -> None:
    headers = auth_headers("unknownsym_pf")
    response = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZDOESNOTEXIST"), headers=headers
    )
    assert response.status_code == 404


def test_add_rejects_non_positive_quantity(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF3")
    headers = auth_headers("badqty_pf")
    payload = _add_payload("ZZAPIPF3")
    payload["quantity"] = 0
    response = client.post("/api/v1/portfolio", json=payload, headers=headers)
    assert response.status_code == 422


def test_update_and_delete_are_ownership_scoped(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF4")
    alice_headers = auth_headers("alice_pf")
    bob_headers = auth_headers("bob_pf")
    created = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZAPIPF4"), headers=alice_headers
    ).json()
    holding_id = created["lots"][0]["holding_id"]

    update_response = client.put(
        f"/api/v1/portfolio/{holding_id}", json={"quantity": 5}, headers=bob_headers
    )
    delete_response = client.delete(f"/api/v1/portfolio/{holding_id}", headers=bob_headers)

    assert update_response.status_code == 404
    assert delete_response.status_code == 404


def test_delete_removes_the_holding(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF5")
    headers = auth_headers("delete_pf")
    created = client.post(
        "/api/v1/portfolio", json=_add_payload("ZZAPIPF5"), headers=headers
    ).json()
    holding_id = created["lots"][0]["holding_id"]

    response = client.delete(f"/api/v1/portfolio/{holding_id}", headers=headers)
    assert response.status_code == 200

    second_delete = client.delete(f"/api/v1/portfolio/{holding_id}", headers=headers)
    assert second_delete.status_code == 404


def test_import_requires_authentication() -> None:
    files = {"file": ("holdings.csv", _STANDARD_HEADER + "\n", "text/csv")}
    response = client.post(
        "/api/v1/portfolio/import", files=files, data={"broker": "zerodha"}
    )
    assert response.status_code == 401


def test_import_requires_a_broker_field(db: Session) -> None:
    headers = auth_headers("nobroker_pf")
    files = {"file": ("holdings.csv", _STANDARD_HEADER + "\nTCS,1,1\n", "text/csv")}
    response = client.post("/api/v1/portfolio/import", files=files, headers=headers)
    assert response.status_code == 422


def test_import_rejects_an_invalid_broker_value(db: Session) -> None:
    headers = auth_headers("badbroker_pf")
    response = _import(headers, _STANDARD_HEADER + "\nTCS,1,1\n", "groww")
    assert response.status_code == 422


def test_import_rejects_unsupported_file_extension(db: Session) -> None:
    headers = auth_headers("badext_pf")
    files = {"file": ("holdings.txt", _STANDARD_HEADER + "\nTCS,1,1\n", "text/plain")}
    response = client.post(
        "/api/v1/portfolio/import", files=files, data={"broker": "zerodha"}, headers=headers
    )
    assert response.status_code == 400


def test_import_rejects_empty_file(db: Session) -> None:
    headers = auth_headers("emptyfile_pf")
    response = _import(headers, "", "zerodha")
    assert response.status_code == 400


def test_import_rejects_oversized_file(db: Session) -> None:
    headers = auth_headers("oversized_pf")
    oversized = _STANDARD_HEADER + "\n" + ("A" * (6 * 1024 * 1024))
    response = _import(headers, oversized, "zerodha")
    assert response.status_code == 400


def test_import_returns_mixed_summary(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF6")
    headers = auth_headers("mixedimport_pf")
    csv_text = _STANDARD_HEADER + "\nZZAPIPF6,5,50\nZZDOESNOTEXIST,1,1\n"

    response = _import(headers, csv_text, "zerodha")

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    statuses = {row["symbol"]: row["status"] for row in body["rows"]}
    assert statuses["ZZAPIPF6"] == "imported"
    assert statuses["ZZDOESNOTEXIST"] == "skipped"


def test_import_xlsx_upload(db: Session) -> None:
    import io

    import openpyxl

    _seed_asset(db, "ZZAPIPF7")
    headers = auth_headers("xlsximport_pf")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Instrument", "Qty.", "Avg. cost"])
    ws.append(["ZZAPIPF7", 5, 50])
    buf = io.BytesIO()
    wb.save(buf)

    files = {
        "file": (
            "holdings.xlsx",
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    response = client.post(
        "/api/v1/portfolio/import", files=files, data={"broker": "upstox"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1


def test_two_broker_imports_consolidate_into_one_row(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF8")
    headers = auth_headers("twobroker_pf")

    _import(headers, _STANDARD_HEADER + "\nZZAPIPF8,10,100\n", "zerodha")
    _import(headers, _STANDARD_HEADER + "\nZZAPIPF8,5,120\n", "upstox")

    portfolio = client.get("/api/v1/portfolio", headers=headers).json()
    assert len(portfolio["holdings"]) == 1
    holding = portfolio["holdings"][0]
    assert holding["quantity"] == 15.0
    assert holding["cost_basis"] == 10 * 100 + 5 * 120
    assert {lot["broker"] for lot in holding["lots"]} == {"zerodha", "upstox"}


def test_reimporting_one_broker_does_not_wipe_the_other(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF9")
    headers = auth_headers("noreimportwipe_pf")

    _import(headers, _STANDARD_HEADER + "\nZZAPIPF9,10,100\n", "zerodha")
    _import(headers, _STANDARD_HEADER + "\nZZAPIPF9,5,120\n", "upstox")
    # Re-import zerodha with an unrelated file that drops ZZAPIPF9 entirely.
    _seed_asset(db, "ZZAPIPF10")
    _import(headers, _STANDARD_HEADER + "\nZZAPIPF10,1,1\n", "zerodha")

    portfolio = client.get("/api/v1/portfolio", headers=headers).json()
    holding = next(h for h in portfolio["holdings"] if h["symbol"] == "ZZAPIPF9")
    # Only the upstox lot should remain for ZZAPIPF9.
    assert holding["quantity"] == 5.0
    assert {lot["broker"] for lot in holding["lots"]} == {"upstox"}


def test_import_only_touches_the_caller_s_own_holdings(db: Session) -> None:
    _seed_asset(db, "ZZAPIPF11")
    alice_headers = auth_headers("alice_import_pf")
    bob_headers = auth_headers("bob_import_pf")
    client.post("/api/v1/portfolio", json=_add_payload("ZZAPIPF11"), headers=bob_headers)

    _import(alice_headers, _STANDARD_HEADER + "\nZZAPIPF11,9,99\n", "zerodha")

    bob_portfolio = client.get("/api/v1/portfolio", headers=bob_headers).json()
    assert bob_portfolio["holdings"][0]["quantity"] == 10  # untouched by Alice's import
