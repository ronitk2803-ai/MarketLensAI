"""News: cache-first reads from `news_article`, refreshed at most once per
cooldown window (Build_plan.md §I: "news hourly") — same provider_fetch_log
-backed pattern used for prices (app/services/prices.py), so repeated page
loads don't repeatedly hit Google News for no new data.
"""

import datetime as dt
import time

from sqlalchemy.orm import Session

from app.db.models import Asset, NewsArticle, ProviderFetchLog
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.fetch_log import record_fetch
from app.providers.india.google_news import GoogleNewsProvider

NEWS_REFRESH_ENDPOINT = "news_refresh"
NEWS_LOOKBACK = dt.timedelta(days=30)
REFRESH_COOLDOWN = dt.timedelta(hours=1)


def _recently_attempted(db: Session, asset_id: int) -> bool:
    last = (
        db.query(ProviderFetchLog)
        .filter_by(asset_id=asset_id, endpoint=NEWS_REFRESH_ENDPOINT)
        .order_by(ProviderFetchLog.fetched_at.desc())
        .first()
    )
    if last is None:
        return False
    fetched_at = last.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - fetched_at) < REFRESH_COOLDOWN


def get_or_fetch_news(db: Session, asset: Asset, *, limit: int = 20) -> list[NewsArticle]:
    if not _recently_attempted(db, asset.id):
        asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
        provider = GoogleNewsProvider()
        since = dt.datetime.now(dt.UTC) - NEWS_LOOKBACK

        started_at = time.monotonic()
        try:
            articles = provider.get_news(asset_ref, since)
            status = "success"
        except ProviderError:
            articles = []
            status = "error"
        latency_ms = round((time.monotonic() - started_at) * 1000)

        record_fetch(
            db,
            provider=provider.name,
            endpoint=NEWS_REFRESH_ENDPOINT,
            asset_id=asset.id,
            status=status,
            latency_ms=latency_ms,
        )

        existing_hashes = {
            row.dedup_hash
            for row in db.query(NewsArticle.dedup_hash).filter(
                NewsArticle.dedup_hash.in_({a.dedup_hash for a in articles})
            )
        }
        for article in articles:
            # Check against both already-stored rows and this same batch —
            # a provider isn't guaranteed to dedupe its own response, and an
            # unflushed add earlier in this loop wouldn't be visible to a
            # fresh query (verified live: two same-hash items in one batch
            # otherwise hit the DB's unique constraint on flush).
            if article.dedup_hash in existing_hashes:
                continue
            existing_hashes.add(article.dedup_hash)
            db.add(
                NewsArticle(
                    asset_id=asset.id,
                    url=article.url,
                    source=article.source,
                    published_at=article.published_at,
                    title=article.title,
                    summary=article.summary,
                    dedup_hash=article.dedup_hash,
                )
            )
        db.flush()

    return (
        db.query(NewsArticle)
        .filter_by(asset_id=asset.id)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )
