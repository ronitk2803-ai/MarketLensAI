"""The verified-email gate, across every endpoint it protects.

One file rather than a test per suite: the rule is a single policy, and
what matters is that the *set* of gated endpoints is right — which is much
easier to review as one list than scattered across five files.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import UNVERIFIED_DETAIL
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


# (method, path, json body) for everything that saves something on the
# user's behalf. Adding a write endpoint without adding it here is the
# failure this file exists to catch.
GATED = [
    ("POST", "/api/v1/watchlist/ZZGATE1", None),
    ("DELETE", "/api/v1/watchlist/ZZGATE1", None),
    ("POST", "/api/v1/theses", {"symbol": "ZZGATE1", "title": "t", "body": "b",
                                "stance": "bull", "conviction": 3, "triggers": []}),
    ("PUT", "/api/v1/theses/1", {"status": "closed"}),
    ("DELETE", "/api/v1/theses/1", None),
    ("POST", "/api/v1/portfolio", {"symbol": "ZZGATE1", "quantity": 1, "avg_cost": 1}),
    ("PUT", "/api/v1/portfolio/1", {"quantity": 2, "avg_cost": 2}),
    ("DELETE", "/api/v1/portfolio/1", None),
]

# Endpoints that take a session but deliberately do NOT require a verified
# address, each for a stated reason.
UNGATED = [
    # A read that happens to be a POST because its condition tree won't fit
    # in a query string. Saves nothing.
    ("POST", "/api/v1/screener/run", {"tree": {"op": "and", "children": []}}),
    # Marking your own alerts read. An unverified account has no watchlist
    # and no theses, so it has no alerts to mark.
    ("POST", "/api/v1/alerts/read", None),
]


@pytest.mark.parametrize(("method", "path", "body"), GATED)
def test_gated_endpoints_refuse_an_unverified_account(
    method: str, path: str, body: dict | None
) -> None:
    headers = auth_headers("gate", verified=False)

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"
    assert response.json()["detail"] == UNVERIFIED_DETAIL


@pytest.mark.parametrize(("method", "path", "body"), GATED)
def test_gated_endpoints_get_past_the_gate_once_verified(
    method: str, path: str, body: dict | None
) -> None:
    """Not asserting success — most of these 404 on a symbol or id that
    doesn't exist. The point is only that the gate is no longer what stops
    them, which a 403 would prove it still was."""
    headers = auth_headers("gate", verified=True)

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code != 403


@pytest.mark.parametrize(("method", "path", "body"), UNGATED)
def test_ungated_endpoints_still_work_for_an_unverified_account(
    method: str, path: str, body: dict | None
) -> None:
    headers = auth_headers("ungated", verified=False)

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code != 403


def test_reading_is_never_gated() -> None:
    headers = auth_headers("reader", verified=False)

    for path in ("/api/v1/watchlist", "/api/v1/theses", "/api/v1/portfolio", "/api/v1/alerts"):
        assert client.get(path, headers=headers).status_code == 200, path


def test_the_gate_is_403_not_401_so_the_ui_does_not_bounce_to_login() -> None:
    """401 would mean "your session is bad, sign in again" — it isn't, and
    sending an already-signed-in user back to a login form is a dead end."""
    unverified = client.post(
        "/api/v1/watchlist/ZZGATE1", headers=auth_headers("status", verified=False)
    )
    anonymous = client.post("/api/v1/watchlist/ZZGATE1")

    assert unverified.status_code == 403
    assert anonymous.status_code == 401
