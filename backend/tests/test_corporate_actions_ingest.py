import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction
from app.domain.models import CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.services.corporate_actions import (
    IngestResult,
    get_or_fetch_corporate_actions,
    ingest_corporate_actions,
)

EVENTS = [
    CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0),
    CorporateActionEvent(type="dividend", ex_date=dt.date(2021, 6, 11), amount=3.5),
]


def _make_asset(db: Session) -> Asset:
    asset = Asset(symbol="ZZTEST1", exchange="NSE", market="IN", name="Test Co 1")
    db.add(asset)
    db.flush()
    return asset


def test_ingest_creates_rows(db: Session) -> None:
    asset = _make_asset(db)

    result = ingest_corporate_actions(db, asset.id, EVENTS, source="yfinance_actions")

    assert result == IngestResult(created=2, updated=0, total=2)
    rows = db.query(CorporateAction).filter_by(asset_id=asset.id).all()
    assert {r.type for r in rows} == {"split", "dividend"}


def test_ingest_is_idempotent_on_rerun(db: Session) -> None:
    asset = _make_asset(db)
    ingest_corporate_actions(db, asset.id, EVENTS, source="yfinance_actions")

    result = ingest_corporate_actions(db, asset.id, EVENTS, source="yfinance_actions")

    assert result == IngestResult(created=0, updated=2, total=2)
    rows = db.query(CorporateAction).filter_by(asset_id=asset.id).all()
    assert len(rows) == 2


def test_ingest_updates_changed_ratio(db: Session) -> None:
    asset = _make_asset(db)
    ingest_corporate_actions(db, asset.id, EVENTS, source="yfinance_actions")

    corrected = [CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=3.0)]
    ingest_corporate_actions(db, asset.id, corrected, source="yfinance_actions")

    row = db.query(CorporateAction).filter_by(asset_id=asset.id, type="split").one()
    assert row.ratio == 3.0


def test_get_or_fetch_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    ingest_corporate_actions(db, asset.id, EVENTS, source="yfinance_actions")

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not call the provider when rows are already stored")

    monkeypatch.setattr(YFinanceCorporateActionsProvider, "get_corporate_actions", _boom)

    result = get_or_fetch_corporate_actions(db, asset)

    assert len(result) == 2
    assert {e.type for e in result} == {"split", "dividend"}


def test_get_or_fetch_fetches_and_persists_on_first_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: EVENTS
    )

    result = get_or_fetch_corporate_actions(db, asset)

    assert len(result) == 2
    rows = db.query(CorporateAction).filter_by(asset_id=asset.id).all()
    assert len(rows) == 2


def test_get_or_fetch_returns_empty_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_actions", "simulated outage")

    monkeypatch.setattr(YFinanceCorporateActionsProvider, "get_corporate_actions", fail)

    assert get_or_fetch_corporate_actions(db, asset) == []
