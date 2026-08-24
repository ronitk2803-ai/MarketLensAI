import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, FinancialStatement
from app.domain.models import AssetRef, Ratios, Statements
from app.providers.errors import ProviderError
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider
from app.services.fundamentals import FUNDAMENTALS_TTL, get_or_fetch_ratios, get_or_fetch_statements


def _make_asset(db: Session, symbol: str = "ZZFUND1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Fundamentals Co")
    db.add(asset)
    db.flush()
    return asset


def test_get_or_fetch_ratios_fetches_and_persists_on_first_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    fake_ratios = Ratios(
        asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
        as_of=dt.date.today(),
        values={"debtToEquity": 36.65, "priceToBook": 1.97},
    )
    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", lambda *a, **k: fake_ratios)

    rows = get_or_fetch_ratios(db, asset)

    assert {r.metric: float(r.value) for r in rows} == {"debtToEquity": 36.65, "priceToBook": 1.97}
    assert all(r.confidence == "low" for r in rows)
    assert all(r.source == "yfinance_fundamentals" for r in rows)


def test_get_or_fetch_ratios_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric="beta",
            value=0.157,
            source="yfinance_fundamentals",
            confidence="low",
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not call the provider when rows are already stored")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", _boom)

    rows = get_or_fetch_ratios(db, asset)
    assert len(rows) == 1
    assert rows[0].metric == "beta"


def test_get_or_fetch_ratios_refetches_once_the_cache_is_older_than_the_ttl(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: the cache had no expiry at all before this — a
    company viewed once kept the ratios from that first fetch forever, even
    though several (P/E, P/B, market cap) are price-dependent and genuinely
    change every session. Build_plan.md §I documents "fundamentals
    quarterly" as the intended TTL; this pins that FUNDAMENTALS_TTL is what
    actually governs the cache, not just documentation."""
    asset = _make_asset(db)
    stale_as_of = dt.datetime.now(dt.UTC) - FUNDAMENTALS_TTL - dt.timedelta(days=1)
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric="beta",
            value=Decimal("0.157"),
            source="yfinance_fundamentals",
            confidence="low",
            as_of=stale_as_of,
        )
    )
    db.flush()

    fresh_ratios = Ratios(
        asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
        as_of=dt.date.today(),
        values={"beta": 0.2, "trailingPE": 23.7},
    )
    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", lambda *a, **k: fresh_ratios)

    rows = get_or_fetch_ratios(db, asset)

    assert {r.metric: float(r.value) for r in rows} == {"beta": 0.2, "trailingPE": 23.7}


def test_get_or_fetch_ratios_within_the_ttl_does_not_refetch(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    fresh_as_of = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric="beta",
            value=Decimal("0.157"),
            source="yfinance_fundamentals",
            confidence="low",
            as_of=fresh_as_of,
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not refetch — cache is within the TTL")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", _boom)

    rows = get_or_fetch_ratios(db, asset)
    assert len(rows) == 1 and rows[0].metric == "beta"


def test_get_or_fetch_ratios_falls_back_to_stale_rows_when_the_refetch_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient Yahoo outage hitting a scheduled refresh must not blank
    out ratios that were fine yesterday — stale-but-real beats nothing."""
    asset = _make_asset(db)
    stale_as_of = dt.datetime.now(dt.UTC) - FUNDAMENTALS_TTL - dt.timedelta(days=1)
    db.add(
        FinancialMetric(
            asset_id=asset.id,
            metric="beta",
            value=Decimal("0.157"),
            source="yfinance_fundamentals",
            confidence="low",
            as_of=stale_as_of,
        )
    )
    db.flush()

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", fail)

    rows = get_or_fetch_ratios(db, asset)
    assert len(rows) == 1 and rows[0].metric == "beta"


def test_get_or_fetch_ratios_returns_empty_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", fail)

    assert get_or_fetch_ratios(db, asset) == []


def test_get_or_fetch_statements_fetches_and_persists(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    fake_statements = [
        Statements(
            asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
            period_type="FY",
            period_end=dt.date(2026, 3, 31),
            statement_type="income",
            line_items={"totalRevenue": 10572190000000.0, "netIncome": 438510000000.0},
        ),
        Statements(
            asset=AssetRef(symbol="ZZFUND1", exchange="NSE"),
            period_type="FY",
            period_end=dt.date(2025, 3, 31),
            statement_type="income",
            line_items={"totalRevenue": 5173490000000.0, "netIncome": 352620000000.0},
        ),
    ]
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider, "get_all_statements", lambda *a, **k: fake_statements
    )

    rows = get_or_fetch_statements(db, asset, "income", "FY")

    assert len(rows) == 4  # 2 periods x 2 line items each
    assert rows[0].period_end == dt.date(2026, 3, 31)  # most recent first
    assert {r.line_item for r in rows if r.period_end == dt.date(2026, 3, 31)} == {
        "totalRevenue",
        "netIncome",
    }


def test_get_or_fetch_statements_uses_stored_rows_without_calling_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    db.add(
        FinancialStatement(
            asset_id=asset.id,
            period_type="FY",
            period_end=dt.date(2026, 3, 31),
            statement_type="income",
            line_item="netIncome",
            value=438510000000,
            source="yfinance_fundamentals",
            confidence="low",
        )
    )
    db.flush()

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not call the provider when rows are already stored")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", _boom)

    rows = get_or_fetch_statements(db, asset, "income", "FY")
    assert len(rows) == 1


def test_get_or_fetch_statements_refetches_once_stale_and_falls_back_on_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    stale_as_of = dt.datetime.now(dt.UTC) - FUNDAMENTALS_TTL - dt.timedelta(days=1)
    db.add(
        FinancialStatement(
            asset_id=asset.id,
            period_type="FY",
            period_end=dt.date(2025, 3, 31),
            statement_type="income",
            line_item="netIncome",
            value=Decimal("352620000000"),
            source="yfinance_fundamentals",
            confidence="low",
            as_of=stale_as_of,
        )
    )
    db.flush()

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", fail)

    # Stale + refetch fails -> falls back to the stale row rather than
    # blanking the panel.
    rows = get_or_fetch_statements(db, asset, "income", "FY")
    assert len(rows) == 1 and rows[0].period_end == dt.date(2025, 3, 31)


def test_get_or_fetch_statements_returns_empty_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> None:
        raise ProviderError("yfinance_fundamentals", "simulated outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_all_statements", fail)

    assert get_or_fetch_statements(db, asset) == []


def test_a_concurrent_writer_between_cache_check_and_write_does_not_500(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the exact race that broke the deployed app.

    get_or_fetch_ratios checks the cache, then fetches, then writes. Another
    caller (the nightly scoring job) can commit the same (asset_id, metric)
    rows inside that window, so the write lands on rows that did not exist
    at check time. With a plain INSERT this raises UniqueViolation on
    uq_financial_metric_asset_metric and the request 500s — observed live on
    RELIANCE while the scoring backfill was running.

    The competing commit is injected from the provider stub, which is
    precisely the check->write window, so this is deterministic rather than
    thread-timing dependent.
    """
    from app.db.session import SessionLocal

    asset = _make_asset(db, "ZZFUNDRACE")
    db.commit()  # the competing session must be able to see the asset
    asset_id = asset.id

    values = {"debtToEquity": 12.5, "priceToBook": 3.25}
    fake_ratios = Ratios(
        asset=AssetRef(symbol="ZZFUNDRACE", exchange="NSE"),
        as_of=dt.date.today(),
        values=values,
    )

    def _fetch_and_let_a_competitor_win(*args: object, **kwargs: object) -> Ratios:
        competitor = SessionLocal()
        try:
            for metric, value in values.items():
                competitor.add(
                    FinancialMetric(
                        asset_id=asset_id,
                        metric=metric,
                        value=Decimal(str(value)),
                        source="yfinance_fundamentals",
                        confidence="low",
                    )
                )
            competitor.commit()
        finally:
            competitor.close()
        return fake_ratios

    monkeypatch.setattr(
        YFinanceFundamentalDataProvider, "get_ratios", _fetch_and_let_a_competitor_win
    )

    try:
        rows = get_or_fetch_ratios(db, asset)
        db.commit()

        assert {r.metric: float(r.value) for r in rows} == values
        # Upsert, not duplicate insert: still one row per (asset, metric).
        assert db.query(FinancialMetric).filter_by(asset_id=asset_id).count() == 2
    finally:
        db.rollback()
        db.query(FinancialMetric).filter_by(asset_id=asset_id).delete()
        db.query(Asset).filter_by(id=asset_id).delete()
        db.commit()
