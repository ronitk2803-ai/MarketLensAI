"""AI narrative summary: click-triggered, shared cache, regenerate-on-change.

Unlike fundamentals/news/prices (fetched, cached *real* data), a summary is
a generated interpretation of that data — so it deliberately does not
follow the TTL-refresh pattern the rest of this module uses. It is
generated once per asset per "something the summary is based on actually
changed" (new news, a moved price, refreshed fundamentals), and every
click after that — from any user, not just the one who triggered the
first generation — reads that same cached row. Combined with the LLM call
only ever happening from a user's explicit click (never a page load or a
schedule), this is what keeps usage inside a free-tier rate limit no
matter how much traffic the page gets (2026-08-24 design chat).

`source_hash` is the mechanism: a fingerprint of the inputs a generation
was built from, not of the generated text. Two calls with the same
fingerprint would produce essentially the same summary from the model, so
the second call is a wasted (rate-limited) API call — skip it.
"""

import hashlib

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Asset, CompanyAiSummary, FinancialMetric, NewsArticle
from app.providers.ai.gemini_summary import DEFAULT_MODEL, GeminiSummaryProvider
from app.providers.errors import ProviderError
from app.services.adjusted_prices import get_adjusted_bars
from app.services.fundamentals import get_or_fetch_ratios
from app.services.news import get_or_fetch_news

SOURCE = "gemini_summary"
_NEWS_FOR_HASH = 10
_NEWS_FOR_PROMPT = 8


def _source_hash(
    news: list[NewsArticle], ratios: list[FinancialMetric], latest_close: float | None
) -> str:
    parts = [a.dedup_hash for a in news[:_NEWS_FOR_HASH]]
    parts += sorted(f"{r.metric}={r.value}" for r in ratios)
    parts.append(f"close={latest_close}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _build_prompt(
    asset: Asset,
    ratios: list[FinancialMetric],
    news: list[NewsArticle],
    latest_close: float | None,
) -> str:
    ratio_lines = "\n".join(f"- {r.metric}: {r.value}" for r in ratios)
    news_lines = "\n".join(f"- {a.title}" for a in news[:_NEWS_FOR_PROMPT])
    return (
        "You are a neutral financial-data assistant. Using only the data "
        "below, write a concise 3-4 sentence plain-English summary of what "
        f"is currently going on with {asset.name} ({asset.symbol}). State "
        "facts drawn from the data, not investment advice, opinions, or "
        "price predictions. If a section below is empty, say that "
        "coverage is limited rather than inventing detail.\n\n"
        f"Latest close: {latest_close if latest_close is not None else 'unavailable'}\n\n"
        f"Key ratios:\n{ratio_lines or '(none available)'}\n\n"
        f"Recent headlines:\n{news_lines or '(no recent news)'}"
    )


def get_cached_summary(db: Session, asset: Asset) -> CompanyAiSummary | None:
    """Read-only — never generates. Safe to call on every page load."""
    return db.query(CompanyAiSummary).filter_by(asset_id=asset.id).one_or_none()


def generate_summary(db: Session, asset: Asset, *, force: bool = False) -> CompanyAiSummary:
    """User-triggered (the button). Cache-aware: only calls the LLM when
    there is no cached row yet, or the underlying data changed since the
    one that's cached — everything else is a free re-read."""
    ratios = get_or_fetch_ratios(db, asset)
    news = get_or_fetch_news(db, asset)
    bars, _ = get_adjusted_bars(db, asset, lookback_days=5)
    latest_close = float(bars[-1].close) if bars else None

    current_hash = _source_hash(news, ratios, latest_close)
    existing = get_cached_summary(db, asset)
    if existing is not None and not force and existing.source_hash == current_hash:
        return existing

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ProviderError("gemini_summary", "GEMINI_API_KEY not configured")

    prompt = _build_prompt(asset, ratios, news, latest_close)
    text = GeminiSummaryProvider(settings.gemini_api_key).generate(prompt)

    row = {
        "asset_id": asset.id,
        "summary": text,
        "source_hash": current_hash,
        "model": DEFAULT_MODEL,
    }
    statement = pg_insert(CompanyAiSummary).values(row)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["asset_id"],
            set_={
                "summary": statement.excluded.summary,
                "source_hash": statement.excluded.source_hash,
                "model": statement.excluded.model,
                "generated_at": func.now(),
            },
        )
    )
    db.flush()
    summary = get_cached_summary(db, asset)
    assert summary is not None
    return summary
