import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction, PriceOHLCV
from app.services.opportunities import (
    run_ranked_screen,
    run_ranked_screen_with_sparklines,
    run_screen,
)


def _add_bars(db: Session, asset: Asset, closes: list[float]) -> None:
    today = dt.date.today()
    n = len(closes)
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=today - dt.timedelta(days=n - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.flush()


def test_run_screen_finds_down_stock_among_seeded_assets(db: Session) -> None:
    down = Asset(symbol="ZZOPP1", exchange="NSE", market="IN", name="Down Co")
    flat = Asset(symbol="ZZOPP2", exchange="NSE", market="IN", name="Flat Co")
    db.add_all([down, flat])
    db.flush()
    _add_bars(db, down, [100.0] * 10 + [70.0])  # -30% over 10d
    _add_bars(db, flat, [100.0] * 11)

    hits = run_screen(db, "down_10d", lookback_days=60)

    symbols = {h.asset.symbol for h in hits}
    assert "ZZOPP1" in symbols
    assert "ZZOPP2" not in symbols


def test_run_screen_excludes_etfs(db: Session) -> None:
    """A real live find: an ETF unit consolidation isn't tracked by our
    corporate-actions source the way a stock split is, so an unclassified
    ETF can look like a ~90% crash. Screens must only scan real equities."""
    etf = Asset(
        symbol="ZZOPPETF", exchange="NSE", market="IN", name="Test ETF", asset_class="ETF"
    )
    db.add(etf)
    db.flush()
    _add_bars(db, etf, [100.0] * 10 + [10.0])  # -90%, would otherwise be a huge hit

    hits = run_screen(db, "down_10d", lookback_days=60)

    assert "ZZOPPETF" not in {h.asset.symbol for h in hits}


def test_run_screen_raises_for_unknown_screen(db: Session) -> None:
    with pytest.raises(ValueError, match="unknown screen"):
        run_screen(db, "not_a_real_screen")


def test_run_screen_excludes_inactive_assets(db: Session) -> None:
    inactive = Asset(
        symbol="ZZOPP3", exchange="NSE", market="IN", name="Inactive Co", active=False
    )
    db.add(inactive)
    db.flush()
    _add_bars(db, inactive, [100.0] * 10 + [50.0])  # would otherwise be a huge hit

    hits = run_screen(db, "down_10d", lookback_days=60)

    assert "ZZOPP3" not in {h.asset.symbol for h in hits}


def test_run_screen_uses_corporate_action_adjusted_bars(db: Session) -> None:
    """A raw ~50% mechanical drop from an unadjusted bonus must NOT trigger
    a decline screen once the stored corporate action is applied — this is
    exactly the "a split must not look like a crash" correctness guarantee
    (Build_plan.md D-007) and the reason screens must adjust before scoring."""
    asset = Asset(symbol="ZZOPP4", exchange="NSE", market="IN", name="Bonus Co")
    db.add(asset)
    db.flush()

    today = dt.date.today()
    bonus_date = today - dt.timedelta(days=5)
    # Flat at 200 pre-bonus, mechanically halves to ~100 on the bonus date,
    # then stays flat post-bonus -> real economic move is ~0%.
    closes = [200.0] * 5 + [100.0] * 6
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=today - dt.timedelta(days=len(closes) - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.add(
        CorporateAction(
            asset_id=asset.id,
            type="bonus",
            ex_date=bonus_date,
            ratio=Decimal("2.0"),
            source="test",
        )
    )
    db.flush()

    hits = run_screen(db, "down_10d", lookback_days=60)

    assert "ZZOPP4" not in {h.asset.symbol for h in hits}


def _add_score(db: Session, asset: Asset, value: float, coverage: float = 1.0) -> None:
    from app.db.models import Score, ScoreProfile

    profile = db.query(ScoreProfile).filter_by(industry_code="default").first()
    if profile is None:
        profile = ScoreProfile(industry_code="default", version=1, weights={"x": 1.0})
        db.add(profile)
        db.flush()
    db.add(
        Score(
            asset_id=asset.id,
            profile_id=profile.id,
            value=Decimal(str(value)),
            coverage=Decimal(str(coverage)),
            confidence="high",
        )
    )
    db.flush()


def test_run_ranked_screen_reorders_by_opportunity_score(db: Session) -> None:
    """The founder_vision.md scenario, end to end through the service."""
    stock_a = Asset(symbol="ZZRANKA", exchange="NSE", market="IN", name="Weak Fundamentals Co")
    stock_b = Asset(symbol="ZZRANKB", exchange="NSE", market="IN", name="Stable Fundamentals Co")
    db.add_all([stock_a, stock_b])
    db.flush()
    _add_bars(db, stock_a, [100.0] * 10 + [70.0])  # -30%
    _add_bars(db, stock_b, [100.0] * 10 + [78.0])  # -22%
    _add_score(db, stock_a, 25.0)
    _add_score(db, stock_b, 75.0)

    ranked = run_ranked_screen(db, "down_10d", lookback_days=60)

    symbols = [r.hit.asset.symbol for r in ranked]
    assert symbols.index("ZZRANKB") < symbols.index("ZZRANKA")


def test_run_ranked_screen_handles_hits_with_no_score_yet(db: Session) -> None:
    down = Asset(symbol="ZZRANKC", exchange="NSE", market="IN", name="Unscored Co")
    db.add(down)
    db.flush()
    _add_bars(db, down, [100.0] * 10 + [70.0])

    ranked = run_ranked_screen(db, "down_10d", lookback_days=60)

    hit = next(r for r in ranked if r.hit.asset.symbol == "ZZRANKC")
    assert hit.opportunity_score is None


def test_sparklines_are_returned_per_hit_oldest_first(db: Session) -> None:
    asset = Asset(symbol="ZZSPARK1", exchange="NSE", market="IN", name="Spark Co")
    db.add(asset)
    db.flush()
    closes = [100.0] * 10 + [70.0]
    _add_bars(db, asset, closes)

    result = run_ranked_screen_with_sparklines(db, "down_10d")

    spark = result.sparklines["ZZSPARK1"]
    assert spark == closes  # oldest first, and the decline is the last point
    assert spark[-1] == 70.0


def test_sparklines_are_capped_to_the_requested_sessions(db: Session) -> None:
    asset = Asset(symbol="ZZSPARK2", exchange="NSE", market="IN", name="Long Co")
    db.add(asset)
    db.flush()
    _add_bars(db, asset, [100.0] * 40 + [70.0])

    result = run_ranked_screen_with_sparklines(db, "down_10d", sessions=5)

    assert len(result.sparklines["ZZSPARK2"]) == 5


def test_short_window_screens_still_get_a_full_length_sparkline(db: Session) -> None:
    """down_5d only needs 6 sessions to evaluate.

    Sizing the load off the screen alone would hand this row a 6-point stub
    while below_dma200 got a full month, so the loader takes the max of the
    screen's requirement and the sparkline length.
    """
    asset = Asset(symbol="ZZSPARK3", exchange="NSE", market="IN", name="Short Window Co")
    db.add(asset)
    db.flush()
    _add_bars(db, asset, [100.0] * 40 + [70.0])

    result = run_ranked_screen_with_sparklines(db, "down_5d", sessions=30)

    assert len(result.sparklines["ZZSPARK3"]) == 30


def test_sparklines_use_corporate_action_adjusted_closes(db: Session) -> None:
    """The sparkline must not draw a cliff the split created.

    Raw closes here are 200 for six sessions, then a 2:1 split, then a real
    decline from 100 to 70. Unadjusted that renders as a 65% collapse; the
    honest picture is a flat stretch followed by a 30% fall. Same
    "a split must not look like a crash" guarantee as the screens
    (Build_plan.md D-007) — the series is drawn, so it has to hold there too.
    """
    asset = Asset(symbol="ZZSPARK4", exchange="NSE", market="IN", name="Split Co")
    db.add(asset)
    db.flush()
    _add_bars(db, asset, [200.0] * 6 + [100.0, 90.0, 80.0, 75.0, 70.0])
    db.add(
        CorporateAction(
            asset_id=asset.id,
            ex_date=dt.date.today() - dt.timedelta(days=4),
            # Lowercase: ADJUSTABLE_ACTION_TYPES is {"split", "bonus"}.
            type="split",
            ratio=Decimal("2"),
            source="test",
        )
    )
    db.flush()

    result = run_ranked_screen_with_sparklines(db, "down_10d")

    spark = result.sparklines["ZZSPARK4"]
    # Pre-split closes halved to 100, so the series never shows the 200 -> 100
    # mechanical step, only the genuine 100 -> 70 decline.
    assert spark[0] == 100.0
    assert spark[-1] == 70.0
    assert max(spark) == 100.0
