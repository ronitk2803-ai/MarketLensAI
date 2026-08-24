import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction, PriceOHLCV
from app.services.watchlist import get_watchlist_quotes


def _add_bars(
    db: Session, asset: Asset, closes: list[float], *, end: dt.date | None = None
) -> None:
    end = end or dt.date.today()
    n = len(closes)
    for i, close in enumerate(closes):
        db.add(
            PriceOHLCV(
                asset_id=asset.id,
                date=end - dt.timedelta(days=n - 1 - i),
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=1000,
                source="test",
            )
        )
    db.flush()


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def test_returns_latest_close_and_as_of(db: Session) -> None:
    asset = _asset(db, "ZZWL1")
    _add_bars(db, asset, [100.0, 105.0, 110.0])

    quotes, unknown = get_watchlist_quotes(db, ["ZZWL1"], delta_days=[7])

    assert unknown == []
    assert quotes[0].close == 110.0
    assert quotes[0].as_of == dt.date.today()


def test_delta_is_computed_against_the_close_n_sessions_back(db: Session) -> None:
    asset = _asset(db, "ZZWL2")
    # 8 bars: index -1 is today, index -(7+1) is 7 sessions back.
    _add_bars(db, asset, [100.0, 100, 100, 100, 100, 100, 100, 140.0])

    quotes, _ = get_watchlist_quotes(db, ["ZZWL2"], delta_days=[7])

    assert quotes[0].deltas[7] == 40.0


def test_a_window_longer_than_available_history_is_simply_absent(db: Session) -> None:
    # "missing, not fabricated" — a 30-session window with only 5 bars must
    # not silently compute against whatever's there or return 0.
    asset = _asset(db, "ZZWL3")
    _add_bars(db, asset, [100.0, 101, 102, 103, 104])

    quotes, _ = get_watchlist_quotes(db, ["ZZWL3"], delta_days=[7, 30])

    assert 7 not in quotes[0].deltas
    assert 30 not in quotes[0].deltas


def test_multiple_delta_windows_are_all_returned(db: Session) -> None:
    asset = _asset(db, "ZZWL4")
    closes = [100.0] * 31
    closes[-8] = 100.0  # 7 sessions back
    closes[-15] = 90.0  # 14 sessions back
    closes[-31] = 80.0  # 30 sessions back
    closes[-1] = 120.0  # today
    _add_bars(db, asset, closes)

    quotes, _ = get_watchlist_quotes(db, ["ZZWL4"], delta_days=[7, 14, 30])

    d = quotes[0].deltas
    assert d[7] == 20.0
    assert round(d[14], 2) == round((120 - 90) / 90 * 100, 2)
    assert d[30] == 50.0


def test_all_time_range_spans_every_stored_bar(db: Session) -> None:
    asset = _asset(db, "ZZWL5")
    _add_bars(db, asset, [50.0, 200.0, 30.0, 100.0])

    quotes, _ = get_watchlist_quotes(db, ["ZZWL5"], delta_days=[7])

    stat = quotes[0].all_time
    assert stat is not None
    assert stat.high == 200.0
    assert stat.low == 30.0
    assert stat.since == dt.date.today() - dt.timedelta(days=3)


def test_position_is_none_when_high_equals_low(db: Session) -> None:
    asset = _asset(db, "ZZWL6")
    _add_bars(db, asset, [100.0, 100.0, 100.0])

    quotes, _ = get_watchlist_quotes(db, ["ZZWL6"], delta_days=[7])

    assert quotes[0].all_time is not None
    assert quotes[0].all_time.position is None


def test_position_reflects_where_the_latest_close_sits_in_the_range(db: Session) -> None:
    asset = _asset(db, "ZZWL7")
    _add_bars(db, asset, [0.0, 100.0, 25.0])  # low=0, high=100, latest=25

    quotes, _ = get_watchlist_quotes(db, ["ZZWL7"], delta_days=[7])

    assert quotes[0].all_time is not None
    assert quotes[0].all_time.position == 0.25


def test_52_week_range_excludes_bars_older_than_a_year(db: Session) -> None:
    asset = _asset(db, "ZZWL8")
    today = dt.date.today()
    # An old spike well outside the 52-week window must not appear as the
    # 52-week high, even though it's still the honest all-time high.
    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=today - dt.timedelta(days=500),
            open=Decimal("500"),
            high=Decimal("500"),
            low=Decimal("500"),
            close=Decimal("500"),
            volume=1000,
            source="test",
        )
    )
    _add_bars(db, asset, [90.0, 100.0, 95.0])
    db.flush()

    quotes, _ = get_watchlist_quotes(db, ["ZZWL8"], delta_days=[7])

    assert quotes[0].all_time is not None and quotes[0].all_time.high == 500.0
    assert quotes[0].week_52 is not None and quotes[0].week_52.high == 100.0


def test_unknown_symbols_are_reported_separately_not_raised(db: Session) -> None:
    asset = _asset(db, "ZZWL9")
    _add_bars(db, asset, [100.0])

    quotes, unknown = get_watchlist_quotes(db, ["ZZWL9", "ZZNOSUCHSTOCK"], delta_days=[7])

    assert {q.symbol for q in quotes} == {"ZZWL9"}
    assert unknown == ["ZZNOSUCHSTOCK"]


def test_a_symbol_with_no_stored_bars_still_returns_a_row_with_nulls(db: Session) -> None:
    _asset(db, "ZZWL10")

    quotes, unknown = get_watchlist_quotes(db, ["ZZWL10"], delta_days=[7])

    assert unknown == []
    assert quotes[0].close is None
    assert quotes[0].as_of is None
    assert quotes[0].all_time is None


def test_spark_is_capped_and_uses_the_most_recent_sessions(db: Session) -> None:
    asset = _asset(db, "ZZWL11")
    closes = [float(i) for i in range(50)]
    _add_bars(db, asset, closes)

    quotes, _ = get_watchlist_quotes(db, ["ZZWL11"], delta_days=[7])

    assert len(quotes[0].spark) == 30
    assert quotes[0].spark[-1] == 49.0


def test_range_stats_use_corporate_action_adjusted_bars(db: Session) -> None:
    # A raw 2:1 split would make the pre-split price look like the all-time
    # high when it was never a real price level post-adjustment.
    asset = _asset(db, "ZZWL12")
    _add_bars(db, asset, [200.0] * 3 + [100.0, 105.0, 95.0])
    db.add(
        CorporateAction(
            asset_id=asset.id,
            ex_date=dt.date.today() - dt.timedelta(days=2),
            type="split",
            ratio=Decimal("2"),
            source="test",
        )
    )
    db.flush()

    quotes, _ = get_watchlist_quotes(db, ["ZZWL12"], delta_days=[7])

    stat = quotes[0].all_time
    assert stat is not None
    # Pre-split 200s adjust down to 100, so the honest high is 105, not 200.
    assert stat.high == 105.0
