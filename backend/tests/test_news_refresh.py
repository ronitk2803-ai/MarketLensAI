"""The nightly news refresh — which assets it picks, and which it doesn't.

The selection is the whole design here: fetching all 500 nightly is what
the job deliberately avoided, so what matters is that this narrows to
assets someone actually cares about and stays capped when a market-wide
selloff makes the screens fire on everything.
"""

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, Holding, Thesis, WatchlistItem
from app.services import news as news_module
from app.services.news import (
    MAX_NIGHTLY_FETCHES,
    followed_asset_ids,
    refresh_tracked_news,
)


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_module.time, "sleep", lambda _s: None)


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _user(db: Session, email: str) -> AppUser:
    user = AppUser(email=email, hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def test_followed_covers_watchlist_holdings_and_theses(db: Session) -> None:
    user = _user(db, "follow@example.com")
    watched = _asset(db, "ZZNEWS1")
    held = _asset(db, "ZZNEWS2")
    thesised = _asset(db, "ZZNEWS3")
    ignored = _asset(db, "ZZNEWS4")

    db.add(WatchlistItem(user_id=user.id, asset_id=watched.id))
    db.add(
        Holding(
            user_id=user.id, asset_id=held.id, broker="manual", quantity=1, avg_cost=1
        )
    )
    db.add(
        Thesis(
            user_id=user.id,
            asset_id=thesised.id,
            title="t",
            body="b",
            stance="bull",
            conviction=3,
        )
    )
    db.flush()

    followed = followed_asset_ids(db)

    assert {watched.id, held.id, thesised.id} <= followed
    assert ignored.id not in followed


def test_refresh_fetches_followed_assets(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db, "fetch@example.com")
    watched = _asset(db, "ZZNEWS5")
    db.add(WatchlistItem(user_id=user.id, asset_id=watched.id))
    db.flush()

    fetched: list[str] = []
    monkeypatch.setattr(
        news_module, "get_or_fetch_news", lambda db, asset: fetched.append(asset.symbol)
    )
    monkeypatch.setattr(news_module, "surfaced_asset_ids", lambda db: set())

    result = refresh_tracked_news(db)

    assert "ZZNEWS5" in fetched
    assert result.fetched >= 1
    assert result.errors == 0


def test_an_asset_fetched_within_the_cooldown_is_skipped(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 1-hour cooldown is what makes a re-run (a catch-up after a missed
    night) nearly free rather than a second full sweep."""
    user = _user(db, "cooldown@example.com")
    watched = _asset(db, "ZZNEWS6")
    db.add(WatchlistItem(user_id=user.id, asset_id=watched.id))
    db.flush()

    monkeypatch.setattr(news_module, "surfaced_asset_ids", lambda db: set())
    monkeypatch.setattr(news_module, "_recently_attempted", lambda db, asset_id: True)
    called: list[str] = []
    monkeypatch.setattr(
        news_module, "get_or_fetch_news", lambda db, asset: called.append(asset.symbol)
    )

    result = refresh_tracked_news(db)

    assert called == []
    assert result.skipped_recent >= 1


def test_the_cap_truncates_surfaced_assets_but_never_followed_ones(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a market-wide selloff the down_* screens fire on hundreds of names
    at once. The cap is what stops that becoming hundreds of Google News
    calls — and followed assets are filled first so it only ever truncates
    the speculative half."""
    user = _user(db, "cap@example.com")
    followed = _asset(db, "ZZNEWSCAP")
    db.add(WatchlistItem(user_id=user.id, asset_id=followed.id))
    db.flush()

    surfaced = [_asset(db, f"ZZSURF{i}") for i in range(MAX_NIGHTLY_FETCHES + 20)]
    monkeypatch.setattr(
        news_module, "surfaced_asset_ids", lambda db: {a.id for a in surfaced}
    )
    fetched: list[str] = []
    monkeypatch.setattr(
        news_module, "get_or_fetch_news", lambda db, asset: fetched.append(asset.symbol)
    )

    result = refresh_tracked_news(db)

    assert len(fetched) <= MAX_NIGHTLY_FETCHES
    assert "ZZNEWSCAP" in fetched  # the followed one survived the cap
    assert result.followed == 1


def test_one_asset_failing_does_not_abort_the_run(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db, "resilient@example.com")
    good = _asset(db, "ZZNEWSOK")
    bad = _asset(db, "ZZNEWSBAD")
    db.add(WatchlistItem(user_id=user.id, asset_id=good.id))
    db.add(WatchlistItem(user_id=user.id, asset_id=bad.id))
    db.flush()

    monkeypatch.setattr(news_module, "surfaced_asset_ids", lambda db: set())

    def flaky(db: Session, asset: Asset) -> None:
        if asset.symbol == "ZZNEWSBAD":
            raise RuntimeError("google news said no")

    monkeypatch.setattr(news_module, "get_or_fetch_news", flaky)

    result = refresh_tracked_news(db)

    assert result.fetched == 1
    assert result.errors == 1


def test_the_prompt_dates_every_headline() -> None:
    """Regression: headlines used to reach the model as bare titles, and
    get_or_fetch_news looks back 30 days — so a month-old item was
    indistinguishable from this morning's and got described as current."""
    from app.db.models import NewsArticle
    from app.engines.scoring.base import ScoreInputs
    from app.services.company_summary import _build_prompt

    class _Asset:
        name = "Test Co"
        symbol = "ZZP"

    article = NewsArticle(
        asset_id=1,
        url="https://example.com/a",
        source="Livemint",
        published_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        title="Something happened",
        dedup_hash="h1",
    )

    prompt = _build_prompt(_Asset(), [], [article], ScoreInputs(), 100.0)  # type: ignore[arg-type]

    assert "2026-07-01 (Livemint): Something happened" in prompt
    assert "newest first" in prompt
