"""News: cache-first reads from `news_article`, refreshed at most once per
cooldown window (Build_plan.md §I: "news hourly") — same provider_fetch_log
-backed pattern used for prices (app/services/prices.py), so repeated page
loads don't repeatedly hit Google News for no new data.
"""

import datetime as dt
import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    Holding,
    NewsArticle,
    ProviderFetchLog,
    Thesis,
    WatchlistItem,
)
from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.fetch_log import record_fetch
from app.providers.india.google_news import GoogleNewsProvider
from app.services.opportunities import run_screen

logger = logging.getLogger(__name__)

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


# --- Nightly refresh for stocks someone actually cares about -----------------

# The screens worth pre-fetching news for. Deliberately only the "something
# just happened" ones: a stock sitting below its 200-DMA has been there for
# months and needs no fresh headline, whereas one that just dropped 10% is
# exactly the case this product exists to explain ("why did it fall?").
TRACKING_SCREENS = ("down_5d", "down_30d", "unusual_volume")

# Hard ceiling on one run. On a market-wide selloff the down_* screens can
# surface hundreds of names at once, and the whole reason the nightly job
# skipped news was to avoid exactly that volume of Google News calls
# (§U.4 flags NSE/scrape hostility; the same caution applies here).
# Followed assets are filled first, so the cap only ever truncates the
# speculative half.
MAX_NIGHTLY_FETCHES = 150

# Small gap between calls. The 1-hour cooldown already stops repeat runs
# from re-fetching, but within a single run this is what keeps 150 requests
# from going out as a burst.
INTER_FETCH_DELAY_SECONDS = 0.3


@dataclass(frozen=True, slots=True)
class NewsRefreshResult:
    followed: int
    surfaced: int
    fetched: int
    skipped_recent: int
    errors: int


def followed_asset_ids(db: Session) -> set[int]:
    """Assets some user has explicitly attached themselves to.

    Watchlisted, held, or carrying a thesis — the three ways this app lets
    someone say "I care about this one". Always refreshed regardless of the
    cap, because these are few and they are the whole point.
    """
    ids: set[int] = set()
    ids.update(row[0] for row in db.query(WatchlistItem.asset_id).distinct())
    ids.update(row[0] for row in db.query(Holding.asset_id).distinct())
    ids.update(row[0] for row in db.query(Thesis.asset_id).distinct())
    return ids


def surfaced_asset_ids(db: Session) -> set[int]:
    """Assets the opportunity screens are currently flagging.

    These are the ones a user is most likely to open next and ask "why?",
    so having the headline already stored is the difference between the AI
    summary explaining the move and saying "(no recent news)".
    """
    symbols: set[str] = set()
    for screen_id in TRACKING_SCREENS:
        try:
            symbols.update(hit.asset.symbol for hit in run_screen(db, screen_id))
        except Exception:
            logger.exception("news refresh: screen %s failed", screen_id)
    if not symbols:
        return set()
    return {
        row[0]
        for row in db.query(Asset.id).filter(
            Asset.symbol.in_(symbols), Asset.market == "IN", Asset.active.is_(True)
        )
    }


def refresh_tracked_news(db: Session) -> NewsRefreshResult:
    """Pre-fetch news for followed and screener-surfaced assets.

    Not the whole universe: that would be ~500 Google News calls a night for
    stocks nobody opens, which is what the original decision to keep news
    lazy was protecting against. This narrows it to the assets where a
    missing headline actually degrades something a user will look at.
    """
    followed = followed_asset_ids(db)
    surfaced = surfaced_asset_ids(db) - followed

    # Followed first, so the cap only ever truncates the speculative half.
    ordered = list(followed) + sorted(surfaced)
    targets = ordered[:MAX_NIGHTLY_FETCHES]

    assets = db.query(Asset).filter(Asset.id.in_(targets)).all() if targets else []

    fetched = 0
    skipped = 0
    errors = 0
    for asset in assets:
        if _recently_attempted(db, asset.id):
            skipped += 1
            continue
        try:
            get_or_fetch_news(db, asset)
            fetched += 1
        except Exception:
            errors += 1
            logger.exception("news refresh: failed for %s", asset.symbol)
        time.sleep(INTER_FETCH_DELAY_SECONDS)

    return NewsRefreshResult(
        followed=len(followed),
        surfaced=len(surfaced),
        fetched=fetched,
        skipped_recent=skipped,
        errors=errors,
    )
