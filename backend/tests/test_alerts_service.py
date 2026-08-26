import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    AppUser,
    Asset,
    CorporateAction,
    PriceOHLCV,
    WatchlistItem,
)
from app.services.alerts import (
    RETENTION_DAYS,
    generate_alerts,
    list_alerts,
    mark_all_read,
    unread_count,
)
from app.services.thesis import TriggerInput, create_thesis, run_thesis_eval


def _user(db: Session, email: str) -> AppUser:
    user = AppUser(email=email, hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _bars(
    db: Session, asset: Asset, closes: list[float], *, volumes: list[int] | None = None
) -> None:
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
                volume=volumes[i] if volumes else 1000,
                source="test",
            )
        )
    db.flush()


def _watch(db: Session, user: AppUser, asset: Asset) -> None:
    db.add(WatchlistItem(user_id=user.id, asset_id=asset.id))
    db.flush()


def _alerts_for(db: Session, user: AppUser, symbol: str) -> list[Alert]:
    return [a for a in list_alerts(db, user.id, limit=200) if a.asset.symbol == symbol]


def test_price_drop_alert_fires_for_a_watched_stock(db: Session) -> None:
    user = _user(db, "drop@example.com")
    asset = _asset(db, "ZZAL1")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [92.0])  # -8% in one session

    generate_alerts(db)

    kinds = {a.kind for a in _alerts_for(db, user, "ZZAL1")}
    assert "price_drop" in kinds


def test_price_surge_is_a_separate_kind_from_a_drop(db: Session) -> None:
    """Directional, like every screen in this app — a two-sided "notable
    move" would be a vocabulary the rest of the product doesn't use."""
    user = _user(db, "surge@example.com")
    asset = _asset(db, "ZZAL2")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [108.0])

    generate_alerts(db)

    kinds = {a.kind for a in _alerts_for(db, user, "ZZAL2")}
    assert "price_surge" in kinds
    assert "price_drop" not in kinds


def test_a_move_below_the_threshold_does_not_alert(db: Session) -> None:
    user = _user(db, "small@example.com")
    asset = _asset(db, "ZZAL3")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [97.0])  # -3%, under the 5% bar

    generate_alerts(db)

    kinds = {a.kind for a in _alerts_for(db, user, "ZZAL3")}
    assert "price_drop" not in kinds


def test_unusual_volume_alert_fires(db: Session) -> None:
    user = _user(db, "volume@example.com")
    asset = _asset(db, "ZZAL4")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 31, volumes=[1000] * 30 + [9000])

    generate_alerts(db)

    kinds = {a.kind for a in _alerts_for(db, user, "ZZAL4")}
    assert "unusual_volume" in kinds


def test_a_corporate_action_on_the_latest_bar_suppresses_price_alerts(db: Session) -> None:
    """adjust_bars handles splits and bonuses only. A special dividend or
    rights issue leaves a real ex-date gap it won't remove, and reporting
    that as a price move would be a fabricated signal."""
    user = _user(db, "exdate@example.com")
    asset = _asset(db, "ZZAL5")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [92.0])
    db.add(
        CorporateAction(
            asset_id=asset.id,
            type="dividend",
            ex_date=dt.date.today(),
            amount=Decimal("8.0"),
            source="test",
        )
    )
    db.flush()

    generate_alerts(db)

    kinds = {a.kind for a in _alerts_for(db, user, "ZZAL5")}
    assert "price_drop" not in kinds


def test_generation_is_idempotent_on_the_same_bar_date(db: Session) -> None:
    """The regression that matters most: the scheduler runs seven days a
    week, so a today-keyed alert would re-announce Friday's drop again on
    Saturday, Sunday and every NSE holiday off an unchanged bar."""
    user = _user(db, "idempotent@example.com")
    asset = _asset(db, "ZZAL6")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [90.0])

    first = generate_alerts(db)
    before = len(_alerts_for(db, user, "ZZAL6"))
    second = generate_alerts(db)
    after = len(_alerts_for(db, user, "ZZAL6"))

    assert first.watchlist_alerts > 0
    assert second.watchlist_alerts == 0
    assert before == after


def test_alerts_are_scoped_to_the_watching_user_only(db: Session) -> None:
    watcher = _user(db, "watcher@example.com")
    bystander = _user(db, "bystander@example.com")
    asset = _asset(db, "ZZAL7")
    _watch(db, watcher, asset)
    _bars(db, asset, [100.0] * 30 + [90.0])

    generate_alerts(db)

    assert _alerts_for(db, watcher, "ZZAL7")
    assert not _alerts_for(db, bystander, "ZZAL7")


def test_thesis_event_produces_exactly_one_alert(db: Session) -> None:
    from app.db.models import FinancialMetric

    user = _user(db, "thesis@example.com")
    asset = _asset(db, "ZZAL8")
    db.add(
        FinancialMetric(
            asset_id=asset.id, metric="debtToEquity", value=Decimal("300"),
            source="test", confidence="low",
        )
    )
    db.flush()
    create_thesis(
        db,
        user_id=user.id,
        asset=asset,
        title="Leverage is the risk",
        body="Because reasons.",
        stance="bear",
        conviction=4,
        triggers=[TriggerInput(metric="debt_to_equity", operator="gt", threshold=150.0)],
    )
    run_thesis_eval(db)

    first = generate_alerts(db)
    second = generate_alerts(db)

    alerts = [a for a in _alerts_for(db, user, "ZZAL8") if a.kind == "thesis_challenged"]
    assert first.thesis_alerts == 1
    assert second.thesis_alerts == 0  # the event is already accounted for
    assert len(alerts) == 1
    assert alerts[0].thesis_event_id is not None


def test_unread_count_and_mark_all_read(db: Session) -> None:
    user = _user(db, "unread@example.com")
    asset = _asset(db, "ZZAL9")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [90.0])
    generate_alerts(db)

    assert unread_count(db, user.id) > 0
    marked = mark_all_read(db, user.id)

    assert marked > 0
    assert unread_count(db, user.id) == 0
    # Marked, never deleted — the row is also the record that this alert
    # was already generated.
    assert _alerts_for(db, user, "ZZAL9")


def test_marking_read_does_not_let_the_alert_regenerate(db: Session) -> None:
    user = _user(db, "reread@example.com")
    asset = _asset(db, "ZZAL10")
    _watch(db, user, asset)
    _bars(db, asset, [100.0] * 30 + [90.0])
    generate_alerts(db)
    before = len(_alerts_for(db, user, "ZZAL10"))
    mark_all_read(db, user.id)

    generate_alerts(db)

    assert len(_alerts_for(db, user, "ZZAL10")) == before
    assert unread_count(db, user.id) == 0


def test_retention_drops_old_read_alerts_but_keeps_unread_ones(db: Session) -> None:
    user = _user(db, "retention@example.com")
    asset = _asset(db, "ZZAL11")
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=RETENTION_DAYS + 5)
    db.add_all(
        [
            Alert(
                user_id=user.id, asset_id=asset.id, kind="price_drop",
                title="old and read", body=None, dedup_key="old-read",
                as_of=dt.date.today(), read_at=old,
            ),
            Alert(
                user_id=user.id, asset_id=asset.id, kind="price_drop",
                title="old but unread", body=None, dedup_key="old-unread",
                as_of=dt.date.today(), read_at=None,
            ),
        ]
    )
    db.flush()

    result = generate_alerts(db)

    titles = {a.title for a in list_alerts(db, user.id, limit=200)}
    assert result.pruned >= 1
    assert "old and read" not in titles
    # Never delete something the user hasn't seen, however old.
    assert "old but unread" in titles


def test_list_alerts_can_filter_to_unread(db: Session) -> None:
    user = _user(db, "filter@example.com")
    asset = _asset(db, "ZZAL12")
    db.add_all(
        [
            Alert(
                user_id=user.id, asset_id=asset.id, kind="price_drop", title="read one",
                body=None, dedup_key="f-read", as_of=dt.date.today(),
                read_at=dt.datetime.now(dt.UTC),
            ),
            Alert(
                user_id=user.id, asset_id=asset.id, kind="price_drop", title="unread one",
                body=None, dedup_key="f-unread", as_of=dt.date.today(), read_at=None,
            ),
        ]
    )
    db.flush()

    titles = {a.title for a in list_alerts(db, user.id, unread_only=True, limit=50)}

    assert titles == {"unread one"}


def test_generate_alerts_is_safe_with_no_watchlists_or_theses(db: Session) -> None:
    result = generate_alerts(db)
    assert result.thesis_alerts >= 0
