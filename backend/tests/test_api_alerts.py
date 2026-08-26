import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Alert, AppUser, Asset
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


def _auth_headers(email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_alert(db: Session, email: str, symbol: str, *, dedup: str, read: bool = False) -> None:
    user = db.query(AppUser).filter_by(email=email).one()
    asset = db.query(Asset).filter_by(symbol=symbol).one_or_none()
    if asset is None:
        asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
        db.add(asset)
        db.flush()
    db.add(
        Alert(
            user_id=user.id,
            asset_id=asset.id,
            kind="price_drop",
            title=f"{symbol} fell 8.0% in one session",
            body="On your watchlist.",
            dedup_key=dedup,
            as_of=dt.date.today(),
            read_at=dt.datetime.now(dt.UTC) if read else None,
        )
    )
    db.flush()


def test_list_requires_authentication() -> None:
    assert client.get("/api/v1/alerts").status_code == 401


def test_mark_read_requires_authentication() -> None:
    assert client.post("/api/v1/alerts/read").status_code == 401


def test_list_returns_the_caller_s_alerts_with_an_unread_count(db: Session) -> None:
    headers = _auth_headers("alertapi1@example.com")
    _seed_alert(db, "alertapi1@example.com", "ZZAPIAL1", dedup="a1")

    body = client.get("/api/v1/alerts", headers=headers).json()

    assert body["unread_count"] == 1
    assert len(body["alerts"]) == 1
    row = body["alerts"][0]
    assert row["symbol"] == "ZZAPIAL1"
    assert row["kind"] == "price_drop"
    # The bar date the signal came from — these are EOD figures surfaced
    # hours after the close.
    assert row["as_of"] is not None


def test_list_never_shows_another_user_s_alerts(db: Session) -> None:
    alice_headers = _auth_headers("alertalice@example.com")
    _auth_headers("alertbob@example.com")
    _seed_alert(db, "alertbob@example.com", "ZZAPIAL2", dedup="a2")

    body = client.get("/api/v1/alerts", headers=alice_headers).json()

    assert body["alerts"] == []
    assert body["unread_count"] == 0


def test_unread_filter(db: Session) -> None:
    headers = _auth_headers("alertfilter@example.com")
    _seed_alert(db, "alertfilter@example.com", "ZZAPIAL3", dedup="a3-read", read=True)
    _seed_alert(db, "alertfilter@example.com", "ZZAPIAL4", dedup="a4-unread")

    all_body = client.get("/api/v1/alerts", headers=headers).json()
    unread_body = client.get("/api/v1/alerts?unread=true", headers=headers).json()

    assert len(all_body["alerts"]) == 2
    assert len(unread_body["alerts"]) == 1
    assert unread_body["alerts"][0]["symbol"] == "ZZAPIAL4"


def test_limit_is_bounded(db: Session) -> None:
    headers = _auth_headers("alertlimit@example.com")

    assert client.get("/api/v1/alerts?limit=201", headers=headers).status_code == 422
    assert client.get("/api/v1/alerts?limit=0", headers=headers).status_code == 422
    assert client.get("/api/v1/alerts?limit=50", headers=headers).status_code == 200


def test_mark_read_zeroes_the_count_without_deleting(db: Session) -> None:
    headers = _auth_headers("alertread@example.com")
    _seed_alert(db, "alertread@example.com", "ZZAPIAL5", dedup="a5")

    marked = client.post("/api/v1/alerts/read", headers=headers).json()
    body = client.get("/api/v1/alerts", headers=headers).json()

    assert marked["marked_read"] == 1
    assert body["unread_count"] == 0
    # Still listed — marking read is acknowledgement, not deletion.
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["read_at"] is not None


def test_auth_me_carries_the_unread_count(db: Session) -> None:
    """The header bell reads this rather than a second endpoint, so it
    costs no extra round trip per page render."""
    headers = _auth_headers("alertme@example.com")

    before = client.get("/api/v1/auth/me", headers=headers).json()
    _seed_alert(db, "alertme@example.com", "ZZAPIAL6", dedup="a6")
    after = client.get("/api/v1/auth/me", headers=headers).json()

    assert before["unread_alert_count"] == 0
    assert after["unread_alert_count"] == 1
