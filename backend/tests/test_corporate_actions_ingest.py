import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction
from app.domain.models import CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.nse_actions import NSECorporateActionsProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.services.corporate_actions import (
    IngestResult,
    get_or_fetch_corporate_actions,
    ingest_corporate_actions,
    refresh_corporate_actions_from_nse,
)

EVENTS = [
    CorporateActionEvent(type="split", ex_date=dt.date(2024, 10, 28), ratio=2.0),
    CorporateActionEvent(type="dividend", ex_date=dt.date(2021, 6, 11), amount=3.5),
]


def _make_asset(db: Session, symbol: str = "ZZTEST1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Co 1")
    db.add(asset)
    db.flush()
    return asset


def _fail(name: str) -> "object":
    def _raise(*args: object, **kwargs: object) -> list[CorporateActionEvent]:
        raise ProviderError(name, "simulated outage")

    return _raise


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
        raise AssertionError("should not call any provider when rows are already stored")

    monkeypatch.setattr(NSECorporateActionsProvider, "get_corporate_actions", _boom)
    monkeypatch.setattr(YFinanceCorporateActionsProvider, "get_corporate_actions", _boom)

    result = get_or_fetch_corporate_actions(db, asset)

    assert len(result) == 2
    assert {e.type for e in result} == {"split", "dividend"}


def test_get_or_fetch_prefers_nse_over_yfinance(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NSE is the primary source (Build_plan.md §F/§6, API_Sources.md §6) —
    if it succeeds, yfinance must not even be called."""
    asset = _make_asset(db)
    monkeypatch.setattr(
        NSECorporateActionsProvider, "get_corporate_actions", lambda *a, **k: EVENTS
    )

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("yfinance should not be called when NSE succeeds")

    monkeypatch.setattr(YFinanceCorporateActionsProvider, "get_corporate_actions", _boom)

    result = get_or_fetch_corporate_actions(db, asset)

    assert len(result) == 2
    rows = db.query(CorporateAction).filter_by(asset_id=asset.id).all()
    assert len(rows) == 2
    assert {r.source for r in rows} == {"nse_actions"}


def test_get_or_fetch_falls_back_to_yfinance_when_nse_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(NSECorporateActionsProvider, "get_corporate_actions", _fail("nse_actions"))
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: EVENTS
    )

    result = get_or_fetch_corporate_actions(db, asset)

    assert len(result) == 2
    rows = db.query(CorporateAction).filter_by(asset_id=asset.id).all()
    assert {r.source for r in rows} == {"yfinance_actions"}


def test_get_or_fetch_returns_empty_when_nse_reports_no_actions(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean empty list from NSE is a real answer (this asset genuinely
    has no actions), not a failure — yfinance must not be tried after it."""
    asset = _make_asset(db)
    monkeypatch.setattr(NSECorporateActionsProvider, "get_corporate_actions", lambda *a, **k: [])

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("yfinance should not be called after a clean empty NSE result")

    monkeypatch.setattr(YFinanceCorporateActionsProvider, "get_corporate_actions", _boom)

    assert get_or_fetch_corporate_actions(db, asset) == []


def test_get_or_fetch_returns_empty_when_both_providers_fail(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(NSECorporateActionsProvider, "get_corporate_actions", _fail("nse_actions"))
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", _fail("yfinance_actions")
    )

    assert get_or_fetch_corporate_actions(db, asset) == []


def test_refresh_from_nse_ingests_only_matching_symbols(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db, "ZZTEST1")
    other = _make_asset(db, "ZZTEST2")

    monkeypatch.setattr(
        "app.services.corporate_actions.fetch_actions_bulk",
        lambda *a, **k: {
            "ZZTEST1": EVENTS,
            "ZZNOTINUNIVERSE": [
                CorporateActionEvent(type="bonus", ex_date=dt.date(2025, 1, 1), ratio=2.0)
            ],
        },
    )

    result = refresh_corporate_actions_from_nse(
        db, [asset, other], from_date=dt.date(2020, 1, 1), to_date=dt.date.today()
    )

    assert result == IngestResult(created=2, updated=0, total=2)
    assert db.query(CorporateAction).filter_by(asset_id=asset.id).count() == 2
    assert db.query(CorporateAction).filter_by(asset_id=other.id).count() == 0


def test_refresh_from_nse_returns_zero_result_on_bulk_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(
        "app.services.corporate_actions.fetch_actions_bulk", _fail("nse_actions")
    )

    result = refresh_corporate_actions_from_nse(
        db, [asset], from_date=dt.date(2020, 1, 1), to_date=dt.date.today()
    )

    assert result == IngestResult(created=0, updated=0, total=0)
    assert db.query(CorporateAction).filter_by(asset_id=asset.id).count() == 0
