import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, Score, ScoreProfile
from app.domain.models import AssetRef, Bar, Ratios
from app.engines.scoring.registry import DEFAULT_WEIGHTS
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider
from app.services.scoring import get_active_profile, get_or_compute_score


def _make_asset(db: Session, symbol: str = "ZZSCORE1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Score Co")
    db.add(asset)
    db.flush()
    return asset


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
            delivery_pct=55.0,
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = _linear_bars(60)
    monkeypatch.setattr(NSEBhavcopyProvider, "get_ohlcv", lambda *a, **k: bars)
    monkeypatch.setattr(
        YFinanceCorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )
    monkeypatch.setattr(
        YFinanceFundamentalDataProvider,
        "get_ratios",
        lambda self, asset: Ratios(
            asset=asset,
            as_of=dt.date.today(),
            values={
                "debtToEquity": 0.8,
                "grossMargins": 0.30,
                "revenueGrowth": 0.10,
                "earningsGrowth": 0.05,
                "priceToBook": 2.5,
            },
        ),
    )


def test_get_active_profile_seeds_default_when_missing(db: Session) -> None:
    profile = get_active_profile(db)
    assert profile.industry_code == "default"
    assert profile.weights == DEFAULT_WEIGHTS


def test_get_active_profile_reuses_existing_row(db: Session) -> None:
    first = get_active_profile(db)
    second = get_active_profile(db)
    assert first.id == second.id


def test_get_active_profile_falls_back_to_default_for_unmapped_industry(db: Session) -> None:
    profile = get_active_profile(db, "banking")
    assert profile.industry_code == "default"


def test_get_or_compute_score_computes_and_persists(db: Session) -> None:
    asset = _make_asset(db)

    score, components = get_or_compute_score(db, asset)

    assert score.value is not None
    assert 0 <= float(score.value) <= 100
    assert len(components) == 5
    assert {c.component for c in components} == {
        "valuation",
        "fundamental_quality",
        "growth",
        "technical_setup",
        "participation",
    }


def test_get_or_compute_score_does_not_recompute_within_the_same_day(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    first_score, _ = get_or_compute_score(db, asset)

    call_count = 0

    def _boom(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        raise AssertionError("should not recompute technicals within the same day")

    monkeypatch.setattr("app.services.scoring.compute_technicals", _boom)

    second_score, _ = get_or_compute_score(db, asset)

    assert second_score.id == first_score.id
    assert call_count == 0


def test_get_or_compute_score_is_graceful_with_no_fundamentals(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(YFinanceFundamentalDataProvider, "get_ratios", lambda *a, **k: Ratios(
        asset=AssetRef(symbol=asset.symbol, exchange="NSE"), as_of=dt.date.today(), values={}
    ))

    score, components = get_or_compute_score(db, asset)

    # valuation + fundamental_quality + growth (0.70 weight) unavailable;
    # technical_setup + participation (0.30) still contribute.
    assert score.value is not None
    assert float(score.coverage) == pytest.approx(0.30, abs=0.01)
    assert score.confidence == "low"


def test_get_or_compute_score_reuses_the_same_profile_row(db: Session) -> None:
    asset1 = _make_asset(db, "ZZSCORE2")
    asset2 = _make_asset(db, "ZZSCORE3")

    score1, _ = get_or_compute_score(db, asset1)
    score2, _ = get_or_compute_score(db, asset2)

    assert score1.profile_id == score2.profile_id
    assert db.query(ScoreProfile).filter_by(industry_code="default").count() == 1


def test_scores_are_append_only_across_days(db: Session) -> None:
    """Simulates a second day's run (yesterday's row shouldn't satisfy
    "already computed today") by inserting a Score dated yesterday."""
    asset = _make_asset(db)
    profile = get_active_profile(db)
    yesterday = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db.add(
        Score(
            asset_id=asset.id,
            profile_id=profile.id,
            value=50.0,
            coverage=1.0,
            confidence="high",
            as_of=yesterday,
        )
    )
    db.flush()

    score, _ = get_or_compute_score(db, asset)

    rows = db.query(Score).filter_by(asset_id=asset.id).all()
    assert len(rows) == 2
    assert score.as_of > yesterday


def test_todays_score_boundary_is_measured_in_utc_not_server_local_time(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the clock that defines "today" for the score cache.

    Score.as_of is stamped by Postgres (server_default=func.now(), UTC).
    Deriving the cutoff from the *server local* date instead made the two
    disagree on any host whose date differs from UTC's for part of the day —
    on IST, every request between 00:00 and 05:30 local missed the cache and
    recomputed, re-fetching fundamentals from Yahoo each time.

    The TZ is forced to one guaranteed to disagree with UTC *right now*
    (east of UTC when it is late in the UTC day, west of it when it is
    early), so this fails on the buggy implementation whatever time the
    suite happens to run — rather than only during the window that first
    exposed it.
    """
    import os
    import time as time_module

    from app.services.scoring import _todays_score

    utc_now = dt.datetime.now(dt.UTC)
    # UTC+14 rolls local past midnight late in the UTC day; UTC-11 holds
    # local on the previous date early in it. Either way local date != UTC
    # date, which is the condition the bug needs to show itself.
    forced_tz = "Etc/GMT-14" if utc_now.hour >= 10 else "Etc/GMT+11"
    monkeypatch.setitem(os.environ, "TZ", forced_tz)
    time_module.tzset()
    try:
        assert dt.date.today() != utc_now.date(), "TZ setup failed to diverge from UTC"

        asset = _make_asset(db, "ZZSCORETZ")
        profile = get_active_profile(db)
        utc_day_start = dt.datetime.combine(utc_now.date(), dt.time.min, tzinfo=dt.UTC)

        stale = Score(
            asset_id=asset.id,
            profile_id=profile.id,
            value=None,
            coverage=Decimal("0"),
            confidence="low",
            as_of=utc_day_start - dt.timedelta(seconds=1),
        )
        db.add(stale)
        db.flush()
        assert _todays_score(db, asset.id, profile.id) is None

        current = Score(
            asset_id=asset.id,
            profile_id=profile.id,
            value=None,
            coverage=Decimal("0"),
            confidence="low",
            as_of=utc_day_start + dt.timedelta(seconds=1),
        )
        db.add(current)
        db.flush()
        found = _todays_score(db, asset.id, profile.id)
        assert found is not None and found.id == current.id
    finally:
        # monkeypatch restores the env var, but the C-level tz cache needs an
        # explicit reset or every later test inherits the forced zone.
        monkeypatch.undo()
        time_module.tzset()
