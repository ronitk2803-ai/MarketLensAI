import dataclasses
import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.db.session import get_db
from app.domain.models import AssetRef, Quote
from app.main import app
from app.services import quotes as quotes_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_test_session(db: Session) -> Iterator[None]:
    quotes_service.clear_cache()

    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    quotes_service.clear_cache()


class _StubProvider:
    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
        return self._quotes


def _seed(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def test_returns_live_quote_with_derived_change_pct(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db, "ZZAPIQ1")
    monkeypatch.setattr(
        quotes_service,
        "_provider",
        _StubProvider(
            {
                "NSE:ZZAPIQ1": Quote(
                    asset=AssetRef(symbol="ZZAPIQ1", exchange="NSE", market="IN"),
                    ltp=110.0,
                    as_of=dt.datetime.now(dt.UTC),
                    previous_close=100.0,
                    market_state="REGULAR",
                )
            }
        ),
    )

    response = client.get("/api/v1/quotes", params={"symbols": "ZZAPIQ1"})

    assert response.status_code == 200
    body = response.json()
    row = body["data"][0]
    assert row["ltp"] == 110.0
    assert row["change_pct"] == pytest.approx(10.0)
    assert row["market_state"] == "REGULAR"
    assert body["meta"]["confidence"] == "high"


def test_change_pct_is_null_when_previous_close_is_unknown(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db, "ZZAPIQ2")
    monkeypatch.setattr(
        quotes_service,
        "_provider",
        _StubProvider(
            {
                "NSE:ZZAPIQ2": Quote(
                    asset=AssetRef(symbol="ZZAPIQ2", exchange="NSE", market="IN"),
                    ltp=110.0,
                    as_of=dt.datetime.now(dt.UTC),
                    previous_close=None,
                )
            }
        ),
    )

    response = client.get("/api/v1/quotes", params={"symbols": "ZZAPIQ2"})

    assert response.json()["data"][0]["change_pct"] is None


def test_no_quotes_reports_low_confidence(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller is about to render stored closes; the envelope has to say
    it isn't live rather than implying coverage it doesn't have."""
    _seed(db, "ZZAPIQ3")
    monkeypatch.setattr(quotes_service, "_provider", _StubProvider({}))

    body = client.get("/api/v1/quotes", params={"symbols": "ZZAPIQ3"}).json()

    assert body["data"] == []
    assert body["meta"]["confidence"] == "low"


def test_rejects_empty_symbol_list() -> None:
    assert client.get("/api/v1/quotes", params={"symbols": ""}).status_code == 400


def _quote_with_candle(**overrides: object) -> Quote:
    base = Quote(
        asset=AssetRef(symbol="ZZAPIQ4", exchange="NSE", market="IN"),
        ltp=1304.0,
        as_of=dt.datetime.now(dt.UTC),
        previous_close=1316.0,
        market_state="REGULAR",
        day_open=1316.6,
        day_high=1320.0,
        day_low=1303.2,
        day_volume=4834344,
    )
    return dataclasses.replace(base, **overrides)


def test_day_candle_is_exposed_with_ltp_as_its_close(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db, "ZZAPIQ4")
    monkeypatch.setattr(
        quotes_service, "_provider", _StubProvider({"NSE:ZZAPIQ4": _quote_with_candle()})
    )

    candle = client.get("/api/v1/quotes", params={"symbols": "ZZAPIQ4"}).json()["data"][0][
        "day_candle"
    ]

    assert candle == {
        "open": 1316.6,
        "high": 1320.0,
        "low": 1303.2,
        "close": 1304.0,  # the live LTP, not a separate field
        "volume": 4834344,
    }


def test_a_partial_candle_is_suppressed_entirely(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half a candle is worse than none: a missing open renders as a shape
    the session never had."""
    _seed(db, "ZZAPIQ4")
    monkeypatch.setattr(
        quotes_service,
        "_provider",
        _StubProvider({"NSE:ZZAPIQ4": _quote_with_candle(day_open=None)}),
    )

    row = client.get("/api/v1/quotes", params={"symbols": "ZZAPIQ4"}).json()["data"][0]

    assert row["day_candle"] is None
    assert row["ltp"] == 1304.0  # the price itself is still usable
