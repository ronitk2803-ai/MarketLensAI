import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import SectorIndexPe
from app.providers.errors import ProviderError
from app.providers.india.nse_sector_pe import IndexPeRow
from app.services.sector_index import (
    SECTOR_PE_TTL,
    get_or_fetch_sector_index_pe,
    get_sector_pe_for_industry,
)

FAKE_ROWS = [
    IndexPeRow(
        index_name="Nifty Financial Services",
        pe=16.04,
        pb=2.43,
        div_yield=0.94,
        index_date=dt.date(2026, 8, 24),
    ),
    IndexPeRow(
        index_name="Nifty IT", pe=19.52, pb=5.38, div_yield=2.62, index_date=dt.date(2026, 8, 24)
    ),
]


def test_get_or_fetch_sector_index_pe_fetches_and_persists_on_first_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: FAKE_ROWS
    )

    result = get_or_fetch_sector_index_pe(db)

    assert set(result) == {"Nifty Financial Services", "Nifty IT"}
    assert float(result["Nifty Financial Services"].pe) == 16.04
    assert db.query(SectorIndexPe).count() == 2


def test_get_or_fetch_sector_index_pe_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def _fetch(**k: object) -> list[IndexPeRow]:
        calls["n"] += 1
        return FAKE_ROWS

    monkeypatch.setattr("app.services.sector_index.fetch_latest_index_pe", _fetch)

    get_or_fetch_sector_index_pe(db)
    get_or_fetch_sector_index_pe(db)

    assert calls["n"] == 1


def test_get_or_fetch_sector_index_pe_refetches_once_stale(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: FAKE_ROWS
    )
    get_or_fetch_sector_index_pe(db)

    # Push every row's as_of back past the TTL, the same way the
    # fundamentals-service staleness tests do.
    db.query(SectorIndexPe).update(
        {SectorIndexPe.as_of: dt.datetime.now(dt.UTC) - SECTOR_PE_TTL - dt.timedelta(hours=1)}
    )
    db.flush()

    updated_rows = [
        IndexPeRow(
            index_name="Nifty Financial Services",
            pe=17.11,
            pb=2.5,
            div_yield=0.9,
            index_date=dt.date(2026, 8, 25),
        ),
    ]
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: updated_rows
    )

    result = get_or_fetch_sector_index_pe(db)

    assert float(result["Nifty Financial Services"].pe) == 17.11


def test_get_or_fetch_sector_index_pe_falls_back_to_stale_on_provider_error(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: FAKE_ROWS
    )
    get_or_fetch_sector_index_pe(db)
    db.query(SectorIndexPe).update(
        {SectorIndexPe.as_of: dt.datetime.now(dt.UTC) - SECTOR_PE_TTL - dt.timedelta(hours=1)}
    )
    db.flush()

    def _raise(**k: object) -> list[IndexPeRow]:
        raise ProviderError("nse_sector_pe", "NSE is down")

    monkeypatch.setattr("app.services.sector_index.fetch_latest_index_pe", _raise)

    result = get_or_fetch_sector_index_pe(db)

    # Stale-but-real beats nothing — yesterday's figure still stands.
    assert float(result["Nifty Financial Services"].pe) == 16.04


def test_get_sector_pe_for_industry_returns_none_when_no_mapping_exists(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"textiles" and "diversified" have no official Nifty sectoral index
    — this must not guess or fall through to an unrelated index."""
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: FAKE_ROWS
    )

    assert get_sector_pe_for_industry(db, "textiles") is None
    assert get_sector_pe_for_industry(db, "diversified") is None


def test_get_sector_pe_for_industry_returns_none_for_none_industry_code(db: Session) -> None:
    assert get_sector_pe_for_industry(db, None) is None


def test_get_sector_pe_for_industry_returns_the_mapped_index(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.sector_index.fetch_latest_index_pe", lambda **k: FAKE_ROWS
    )

    result = get_sector_pe_for_industry(db, "financial-services")

    assert result is not None
    assert result.index_name == "Nifty Financial Services"
    assert float(result.pe) == 16.04
