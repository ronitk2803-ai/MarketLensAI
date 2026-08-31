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


def test_two_dividends_on_one_ex_date_both_persist(db: Session) -> None:
    """A company routinely pays interim + final + special dividends sharing
    one ex-date (NESTLEIND 2026-07-10 paid ₹5 and ₹2, live). Both must be
    stored, and re-ingesting them must not raise on the now-ambiguous
    (type, ex_date) lookup."""
    asset = _make_asset(db)
    events = [
        CorporateActionEvent(type="dividend", ex_date=dt.date(2026, 7, 10), amount=5.0),
        CorporateActionEvent(type="dividend", ex_date=dt.date(2026, 7, 10), amount=2.0),
    ]

    first = ingest_corporate_actions(db, asset.id, events, source="nse_actions")
    assert first == IngestResult(created=2, updated=0, total=2)

    second = ingest_corporate_actions(db, asset.id, events, source="nse_actions")
    assert second == IngestResult(created=0, updated=2, total=2)

    amounts = sorted(
        float(r.amount)
        for r in db.query(CorporateAction).filter_by(asset_id=asset.id, type="dividend").all()
    )
    assert amounts == [2.0, 5.0]


def test_same_action_listed_twice_in_one_batch_is_deduped(db: Session) -> None:
    """NSE occasionally returns one action twice in a single response (a
    SIYSIL demerger, live 2026-08). With autoflush off the naive loop wrote
    two identical rows; the batch must collapse them to one."""
    asset = _make_asset(db)
    dup = CorporateActionEvent(type="demerger", ex_date=dt.date(2026, 8, 21))

    result = ingest_corporate_actions(db, asset.id, [dup, dup], source="nse_actions")

    assert result.created == 1
    assert db.query(CorporateAction).filter_by(asset_id=asset.id).count() == 1


def test_ingest_tolerates_preexisting_duplicate_rows(db: Session) -> None:
    """Rows an earlier pre-fix run duplicated must not make a later ingest
    raise MultipleResultsFound — it updates one and leaves the rest."""
    asset = _make_asset(db)
    for _ in range(2):
        db.add(
            CorporateAction(
                asset_id=asset.id,
                type="demerger",
                ex_date=dt.date(2026, 8, 21),
                source="nse_actions",
            )
        )
    db.flush()

    result = ingest_corporate_actions(
        db,
        asset.id,
        [CorporateActionEvent(type="demerger", ex_date=dt.date(2026, 8, 21))],
        source="nse_actions",
    )

    assert result == IngestResult(created=0, updated=1, total=1)


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
