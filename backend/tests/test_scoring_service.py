import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, Company, FinancialMetric, Industry, Score, ScoreProfile
from app.domain.models import AssetRef, Bar, Ratios
from app.engines.scoring.registry import DEFAULT_WEIGHTS, FINANCIALS_WEIGHTS
from app.providers.india.nse_actions import NSECorporateActionsProvider
from app.providers.india.nse_bhavcopy import NSEBhavcopyProvider
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider
from app.providers.india.yfinance_fundamentals import YFinanceFundamentalDataProvider
from app.services.fundamentals import MIN_SECTOR_SAMPLE
from app.services.scoring import (
    gather_score_inputs,
    get_active_profile,
    get_or_compute_score,
    resolve_profile_for_asset,
)


def _make_asset(db: Session, symbol: str = "ZZSCORE1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test Score Co")
    db.add(asset)
    db.flush()
    return asset


def _classify(db: Session, asset: Asset, code: str, profile_key: str) -> Industry:
    """Give an asset the Company -> Industry linkage profile resolution
    walks. Both hops are separate rows, so tests can also omit either one."""
    industry = db.query(Industry).filter_by(code=code).one_or_none()
    if industry is None:
        industry = Industry(code=code, name=code.title(), score_profile_key=profile_key)
        db.add(industry)
        db.flush()
    db.add(Company(asset_id=asset.id, industry_id=industry.id))
    db.flush()
    return industry


def _financials_profile(db: Session) -> ScoreProfile:
    profile = db.query(ScoreProfile).filter_by(industry_code="financials").one_or_none()
    if profile is None:
        profile = ScoreProfile(
            industry_code="financials", version=1, weights=FINANCIALS_WEIGHTS, active=True
        )
        db.add(profile)
        db.flush()
    return profile


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
        NSECorporateActionsProvider, "get_corporate_actions", lambda *a, **k: []
    )
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
                # debtToEquity in Yahoo's own percentage unit (80.0 == 0.8x).
                "debtToEquity": 80.0,
                "grossMargins": 0.30,
                "revenueGrowth": 0.10,
                "earningsGrowth": 0.05,
                "priceToBook": 2.5,
                "trailingPE": 22.0,
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


def test_resolve_profile_falls_back_to_default_for_an_unclassified_asset(db: Session) -> None:
    """Both hops to an industry are nullable. An asset with no Company row
    isn't an error, it's just unclassified."""
    asset = _make_asset(db, "ZZPROF1")
    assert asset.company is None
    assert resolve_profile_for_asset(db, asset).industry_code == "default"


def test_resolve_profile_falls_back_when_company_has_no_industry(db: Session) -> None:
    asset = _make_asset(db, "ZZPROF2")
    db.add(Company(asset_id=asset.id, industry_id=None))
    db.flush()
    db.refresh(asset)
    assert resolve_profile_for_asset(db, asset).industry_code == "default"


def test_resolve_profile_falls_back_for_an_industry_with_no_seeded_profile(db: Session) -> None:
    asset = _make_asset(db, "ZZPROF3")
    _classify(db, asset, "zz-unmapped-industry", profile_key="not-a-seeded-profile")
    db.refresh(asset)
    assert resolve_profile_for_asset(db, asset).industry_code == "default"


def test_resolve_profile_uses_the_industry_s_score_profile_key(db: Session) -> None:
    """Keyed off Industry.score_profile_key rather than Industry.code, so
    several industries can share one profile."""
    _financials_profile(db)
    asset = _make_asset(db, "ZZPROF4")
    _classify(db, asset, "zz-financial-services", profile_key="financials")
    db.refresh(asset)

    assert resolve_profile_for_asset(db, asset).industry_code == "financials"


def test_resolve_profile_cache_avoids_requerying(db: Session) -> None:
    _financials_profile(db)
    asset = _make_asset(db, "ZZPROF5")
    _classify(db, asset, "zz-fin-cached", profile_key="financials")
    db.refresh(asset)

    cache: dict[str, ScoreProfile] = {}
    first = resolve_profile_for_asset(db, asset, cache=cache)
    assert set(cache) == {"financials"}
    second = resolve_profile_for_asset(db, asset, cache=cache)
    assert first.id == second.id


def test_financials_asset_is_scored_without_fundamental_quality(db: Session) -> None:
    """The whole point of the profile: for a lender, every leg of
    fundamental_quality means something different than it does elsewhere,
    so the component is excluded rather than reweighted."""
    _financials_profile(db)
    asset = _make_asset(db, "ZZPROF6")
    _classify(db, asset, "zz-fin-scored", profile_key="financials")
    db.refresh(asset)

    score, components = get_or_compute_score(db, asset)

    assert score.profile.industry_code == "financials"
    names = {c.component for c in components}
    assert "fundamental_quality" not in names
    assert "earnings_valuation" in names


def test_two_industries_can_share_one_profile(db: Session) -> None:
    financials = _financials_profile(db)
    bank = _make_asset(db, "ZZPROF7")
    nbfc = _make_asset(db, "ZZPROF8")
    _classify(db, bank, "zz-banks", profile_key="financials")
    _classify(db, nbfc, "zz-nbfcs", profile_key="financials")
    db.refresh(bank)
    db.refresh(nbfc)

    assert resolve_profile_for_asset(db, bank).id == financials.id
    assert resolve_profile_for_asset(db, nbfc).id == financials.id


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


def _seed_peer(db: Session, symbol: str, industry: Industry, metric: str, value: float) -> None:
    """A bare peer asset with just one stored FinancialMetric row — enough
    to be a member of the peer group get_sector_ratio_values queries,
    without needing the full technicals/fundamentals stack this file's own
    _make_asset-scored assets go through."""
    peer = Asset(symbol=symbol, exchange="NSE", market="IN", name=symbol)
    db.add(peer)
    db.flush()
    db.add(Company(asset_id=peer.id, industry_id=industry.id))
    db.add(
        FinancialMetric(
            asset_id=peer.id,
            metric=metric,
            value=Decimal(str(value)),
            source="test",
            confidence="low",
        )
    )
    db.flush()


def test_gather_score_inputs_uses_peer_percentile_once_enough_peers_exist(db: Session) -> None:
    asset = _make_asset(db, "ZZSCOREPEER1")
    industry = _classify(db, asset, "ZZPEERIND1", "default")
    # This asset's own trailingPE (22.0, from the autouse fundamentals
    # stub) plus MIN_SECTOR_SAMPLE-1 cheaper peers, so it ranks at the
    # bottom of its own peer group on price — a low percentile despite
    # 22.0 scoring a respectable ~64 on the absolute band.
    assert MIN_SECTOR_SAMPLE >= 2
    for i in range(MIN_SECTOR_SAMPLE - 1):
        _seed_peer(db, f"ZZPEER1{i}", industry, "trailingPE", 5.0 + i)

    inputs = gather_score_inputs(db, asset)

    assert inputs.trailing_pe == pytest.approx(22.0)
    assert inputs.trailing_pe_percentile is not None
    # 22.0 is the most expensive in its own peer group (itself included).
    assert inputs.trailing_pe_percentile == pytest.approx(100.0 / MIN_SECTOR_SAMPLE)


def test_gather_score_inputs_leaves_percentile_none_below_minimum_sample(db: Session) -> None:
    asset = _make_asset(db, "ZZSCOREPEER2")
    industry = _classify(db, asset, "ZZPEERIND2", "default")
    for i in range(MIN_SECTOR_SAMPLE - 2):  # one short of the minimum, including this asset
        _seed_peer(db, f"ZZPEER2{i}", industry, "trailingPE", 10.0 + i)

    inputs = gather_score_inputs(db, asset)

    assert inputs.trailing_pe == pytest.approx(22.0)
    assert inputs.trailing_pe_percentile is None


def test_gather_score_inputs_never_computes_percentiles_for_an_unclassified_asset(
    db: Session,
) -> None:
    asset = _make_asset(db, "ZZSCOREPEER3")  # no Company/Industry row at all

    inputs = gather_score_inputs(db, asset)

    assert inputs.trailing_pe_percentile is None
    assert inputs.price_to_book_percentile is None
    assert inputs.debt_to_equity_percentile is None
    assert inputs.gross_margins_percentile is None
    assert inputs.revenue_growth_percentile is None
    assert inputs.earnings_growth_percentile is None


def test_gather_score_inputs_peer_cache_avoids_requerying(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset1 = _make_asset(db, "ZZSCOREPEER4")
    asset2 = _make_asset(db, "ZZSCOREPEER5")
    industry = _classify(db, asset1, "ZZPEERIND4", "default")
    db.add(Company(asset_id=asset2.id, industry_id=industry.id))
    db.flush()
    for i in range(MIN_SECTOR_SAMPLE):
        _seed_peer(db, f"ZZPEER4{i}", industry, "trailingPE", 15.0 + i)

    import app.services.scoring as scoring_module

    call_count = 0
    real = scoring_module.get_sector_ratio_values

    def _counting(*args: object, **kwargs: object) -> list[float]:
        nonlocal call_count
        call_count += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(scoring_module, "get_sector_ratio_values", _counting)

    cache: dict = {}
    gather_score_inputs(db, asset1, peer_cache=cache)
    gather_score_inputs(db, asset2, peer_cache=cache)

    # 6 metrics queried once each for asset1; asset2 (same industry) must
    # reuse every one of them from the cache rather than requerying.
    assert call_count == 6


def test_gather_score_inputs_lower_is_better_metrics_are_inverted(db: Session) -> None:
    """A cheap P/B (low raw value) must land on a HIGH percentile — every
    ScoreInputs field means "higher = more attractive," peer percentiles
    included."""
    asset = _make_asset(db, "ZZSCOREPEER6")
    industry = _classify(db, asset, "ZZPEERIND6", "default")
    # This asset's own priceToBook (2.5, from the autouse stub) is the
    # cheapest in its peer group.
    for i in range(MIN_SECTOR_SAMPLE - 1):
        _seed_peer(db, f"ZZPEER6{i}", industry, "priceToBook", 10.0 + i)

    inputs = gather_score_inputs(db, asset)

    assert inputs.price_to_book_percentile == pytest.approx(100.0)
