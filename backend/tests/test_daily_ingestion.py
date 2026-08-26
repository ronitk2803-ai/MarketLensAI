import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    Asset,
    CorporateAction,
    FinancialMetric,
    PriceOHLCV,
    ProviderFetchLog,
    Score,
    ScoreComponent,
)
from app.domain.models import Bar, Ratios
from app.jobs.daily_ingestion import run_daily_ingestion
from app.providers.india.nse_bhavcopy import BhavcopyRow, NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider

# run_daily_ingestion commits internally (deliberately — per Build_plan.md,
# one asset's failure shouldn't roll back another asset's successful write),
# so the usual rollback-only `db` fixture can't undo what these tests create.
# Every test must clean up its own committed rows explicitly.
_TEST_SYMBOLS = ("ZZDAILY1", "ZZDAILY2", "ZZDAILYETF", "ZZDAILYINACT")


@pytest.fixture(autouse=True)
def _cleanup_committed_rows(db: Session) -> None:
    yield
    db.rollback()  # clears any PendingRollbackError left by a failed test body
    asset_ids = [
        row[0]
        for row in db.query(Asset.id).filter(Asset.symbol.in_(_TEST_SYMBOLS)).all()
    ]
    if asset_ids:
        db.query(ScoreComponent).filter(
            ScoreComponent.score_id.in_(db.query(Score.id).filter(Score.asset_id.in_(asset_ids)))
        ).delete(synchronize_session=False)
        db.query(Score).filter(Score.asset_id.in_(asset_ids)).delete(synchronize_session=False)
        db.query(PriceOHLCV).filter(PriceOHLCV.asset_id.in_(asset_ids)).delete(synchronize_session=False)
        db.query(CorporateAction).filter(CorporateAction.asset_id.in_(asset_ids)).delete(
            synchronize_session=False
        )
        db.query(ProviderFetchLog).filter(ProviderFetchLog.asset_id.in_(asset_ids)).delete(
            synchronize_session=False
        )
        db.query(FinancialMetric).filter(FinancialMetric.asset_id.in_(asset_ids)).delete(
            synchronize_session=False
        )
        db.query(Alert).filter(Alert.asset_id.in_(asset_ids)).delete(synchronize_session=False)
        db.query(Asset).filter(Asset.id.in_(asset_ids)).delete(synchronize_session=False)
        db.commit()


def _linear_bars(n: int) -> list[Bar]:
    today = dt.date.today()
    return [
        Bar(
            date=today - dt.timedelta(days=n - 1 - i),
            open=100 + i,
            high=100 + i,
            low=100 + i,
            close=100.0 + i,
            volume=1000 + i,
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    today = dt.date.today()
    bars = _linear_bars(60)

    def fake_day_bars(self: NSEBhavcopyProvider, date: dt.date) -> list[BhavcopyRow]:
        match = next((b for b in bars if b.date == date), None)
        if match is None:
            return []
        return [
            BhavcopyRow(
                symbol="ZZDAILY1",
                series="EQ",
                date=date,
                open=match.open,
                high=match.high,
                low=match.low,
                close=match.close,
                volume=match.volume,
                delivery_qty=None,
                delivery_pct=None,
            )
        ]

    monkeypatch.setattr(NSEBhavcopyProvider, "get_day_bars", fake_day_bars)
    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: bars)
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider,
        "get_ratios",
        lambda self, asset: Ratios(
            asset=asset, as_of=today, values={"debtToEquity": 0.5, "priceToBook": 2.0}
        ),
    )


def _make_asset(db: Session, symbol: str = "ZZDAILY1") -> Asset:
    asset = Asset(
        symbol=symbol, exchange="NSE", market="IN", name="Test Daily Co", asset_class="EQUITY"
    )
    db.add(asset)
    db.flush()
    return asset


def test_run_daily_ingestion_end_to_end(db: Session) -> None:
    # The dev DB carries the full seeded universe (~260 assets), so
    # run_daily_ingestion processes all of them, not just this test's asset —
    # assert on this asset's own outcome rather than on global counts.
    asset = _make_asset(db)

    result = run_daily_ingestion(db, price_lookback_days=10, with_alerts=False)

    assert result.corporate_actions_errors == 0
    assert result.scores_errors == 0
    assert result.backfill.bars_persisted > 0

    assert db.query(PriceOHLCV).filter_by(asset_id=asset.id).count() > 0
    assert db.query(Score).filter_by(asset_id=asset.id).count() == 1


def test_run_daily_ingestion_skips_non_equity_and_inactive_assets(db: Session) -> None:
    etf = Asset(
        symbol="ZZDAILYETF", exchange="NSE", market="IN", name="Test ETF", asset_class="ETF"
    )
    inactive = Asset(
        symbol="ZZDAILYINACT",
        exchange="NSE",
        market="IN",
        name="Inactive Co",
        asset_class="EQUITY",
        active=False,
    )
    db.add_all([etf, inactive])
    db.flush()

    run_daily_ingestion(db, price_lookback_days=10, with_alerts=False)

    assert db.query(Score).filter_by(asset_id=etf.id).count() == 0
    assert db.query(Score).filter_by(asset_id=inactive.id).count() == 0
    assert db.query(CorporateAction).filter_by(asset_id=etf.id).count() == 0
    assert db.query(CorporateAction).filter_by(asset_id=inactive.id).count() == 0


def test_run_daily_ingestion_continues_past_a_single_asset_failure(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset1 = _make_asset(db, "ZZDAILY1")
    asset2 = _make_asset(db, "ZZDAILY2")

    def fail(self: object, asset: object) -> None:
        raise RuntimeError("simulated fundamentals outage")

    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", fail)

    result = run_daily_ingestion(db, price_lookback_days=10, with_alerts=False)

    # A fundamentals outage propagates as a genuine per-asset scoring failure
    # (not swallowed into a degraded-but-computed score), and the batch still
    # completes rather than aborting on the first failure.
    assert result.scores_errors >= 2
    assert db.query(Score).filter_by(asset_id=asset1.id).count() == 0
    assert db.query(Score).filter_by(asset_id=asset2.id).count() == 0
