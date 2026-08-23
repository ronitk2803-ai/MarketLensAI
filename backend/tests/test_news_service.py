import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, NewsArticle
from app.domain.models import Article, AssetRef
from app.providers.errors import ProviderError
from app.providers.india.google_news import GoogleNewsProvider
from app.services.news import get_or_fetch_news

RELIANCE_REF = AssetRef(symbol="RELIANCE", exchange="NSE", market="IN")


def _make_asset(db: Session, symbol: str = "ZZNEWS1") -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name="Test News Co")
    db.add(asset)
    db.flush()
    return asset


def _article(title: str, days_ago: int, dedup_hash: str) -> Article:
    return Article(
        url=f"https://example.com/{dedup_hash}",
        source="Test Source",
        published_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
        title=title,
        dedup_hash=dedup_hash,
        asset=RELIANCE_REF,
    )


def test_fetches_and_persists_on_first_call(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _make_asset(db)
    articles = [_article("Story A", 1, "hash-a"), _article("Story B", 2, "hash-b")]
    monkeypatch.setattr(GoogleNewsProvider, "get_news", lambda *a, **k: articles)

    rows = get_or_fetch_news(db, asset)

    assert {r.title for r in rows} == {"Story A", "Story B"}
    assert rows[0].published_at >= rows[1].published_at  # newest first


def test_dedup_hash_prevents_duplicate_rows(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _make_asset(db)
    monkeypatch.setattr(
        GoogleNewsProvider, "get_news", lambda *a, **k: [_article("Story A", 1, "hash-a")]
    )
    get_or_fetch_news(db, asset)

    # Simulate the cooldown having elapsed by clearing the fetch log, then
    # re-fetching the exact same article.
    db.query(NewsArticle).delete()
    from app.db.models import ProviderFetchLog

    db.query(ProviderFetchLog).delete()
    db.flush()

    monkeypatch.setattr(
        GoogleNewsProvider,
        "get_news",
        lambda *a, **k: [_article("Story A", 1, "hash-a"), _article("Story A", 1, "hash-a")],
    )
    get_or_fetch_news(db, asset)

    rows = db.query(NewsArticle).filter_by(dedup_hash="hash-a").all()
    assert len(rows) == 1


def test_does_not_refetch_within_cooldown(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _make_asset(db)
    call_count = 0

    def fake_get_news(*args: object, **kwargs: object) -> list[Article]:
        nonlocal call_count
        call_count += 1
        return [_article("Story A", 1, "hash-a")]

    monkeypatch.setattr(GoogleNewsProvider, "get_news", fake_get_news)

    get_or_fetch_news(db, asset)
    get_or_fetch_news(db, asset)
    get_or_fetch_news(db, asset)

    assert call_count == 1


def test_returns_empty_gracefully_when_provider_fails(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _make_asset(db)

    def fail(*args: object, **kwargs: object) -> list[Article]:
        raise ProviderError("google_news", "simulated outage")

    monkeypatch.setattr(GoogleNewsProvider, "get_news", fail)

    assert get_or_fetch_news(db, asset) == []


def test_respects_limit(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _make_asset(db)
    articles = [_article(f"Story {i}", i, f"hash-{i}") for i in range(5)]
    monkeypatch.setattr(GoogleNewsProvider, "get_news", lambda *a, **k: articles)

    rows = get_or_fetch_news(db, asset, limit=2)
    assert len(rows) == 2
