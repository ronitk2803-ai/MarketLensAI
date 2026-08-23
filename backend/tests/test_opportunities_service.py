import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction, PriceOHLCV
from app.services.opportunities import run_screen


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
