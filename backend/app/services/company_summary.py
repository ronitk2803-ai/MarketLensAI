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
from app.engines.scoring.base import ScoreInputs
from app.providers.ai.gemini_summary import DEFAULT_MODEL, GeminiSummaryProvider
from app.providers.errors import ProviderError
from app.services.adjusted_prices import get_adjusted_bars
from app.services.fundamentals import get_or_fetch_ratios
from app.services.news import get_or_fetch_news
from app.services.scoring import gather_score_inputs

SOURCE = "gemini_summary"
_NEWS_FOR_HASH = 10
_NEWS_FOR_PROMPT = 8


def _source_hash(
    news: list[NewsArticle],
    ratios: list[FinancialMetric],
    inputs: ScoreInputs,
    latest_close: float | None,
) -> str:
    parts = [a.dedup_hash for a in news[:_NEWS_FOR_HASH]]
    parts += sorted(f"{r.metric}={r.value}" for r in ratios)
    # Technicals/volume weren't in the fingerprint before they were in the
    # prompt — RSI crossing into oversold or a volume spike wouldn't have
    # invalidated the cache, so a summary written before that move could
    # sit there stale (an unchanged fundamentals+news fingerprint, but a
    # prompt that now says something different) until something else
    # happened to trigger a regeneration.
    parts.append(
        f"rsi={inputs.rsi14},drawdown={inputs.drawdown_pct},"
        f"relvol={inputs.relative_volume},delivery={inputs.delivery_pct}"
    )
    parts.append(f"close={latest_close}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# Deliberately explicit and repeated, not a single line — a model asked for
# "supporting factors" and "risk factors" drifts toward summarizing them
# into an implicit verdict ("given this, XYZ looks attractive") unless the
# instruction to stop short of that is stated more than once and modelled
# by the required output shape itself.
_NO_ADVICE_RULES = (
    "Rules, all mandatory:\n"
    "- Do not recommend buying, selling, or holding.\n"
    "- Do not say whether now is a good or bad time to invest.\n"
    "- Do not suggest a time horizon (e.g. \"over the next 3-6 months\") or "
    "predict where the price is headed.\n"
    "- Do not use language that implies a verdict, like \"looks attractive\" "
    "or \"warrants caution\" — state the underlying fact and let it stand "
    "on its own.\n"
    "- If you notice yourself about to write a recommendation, stop and "
    "rephrase as a plain observation instead."
)


def _build_prompt(
    asset: Asset,
    ratios: list[FinancialMetric],
    news: list[NewsArticle],
    inputs: ScoreInputs,
    latest_close: float | None,
) -> str:
    ratio_lines = "\n".join(f"- {r.metric}: {r.value}" for r in ratios)
    news_lines = "\n".join(f"- {a.title}" for a in news[:_NEWS_FOR_PROMPT])
    technical_lines = "\n".join(
        line
        for line in [
            f"- RSI (14): {inputs.rsi14}" if inputs.rsi14 is not None else None,
            f"- Drawdown from recent peak: {inputs.drawdown_pct}%"
            if inputs.drawdown_pct is not None
            else None,
            f"- Volume vs its 20-day average: {inputs.relative_volume}x"
            if inputs.relative_volume is not None
            else None,
            f"- Delivery percentage: {inputs.delivery_pct}%"
            if inputs.delivery_pct is not None
            else None,
        ]
        if line is not None
    )
    return (
        "You are a neutral financial-data assistant helping someone do "
        f"their own research on {asset.name} ({asset.symbol}). Using only "
        "the data below:\n\n"
        "1. Write a 2-3 sentence factual synthesis of what the fundamentals, "
        "technicals, volume, and news together currently show.\n"
        "2. List the strongest supporting factors as bullet points under a "
        "\"Supporting factors:\" heading (facts that point toward the "
        "business or the stock's setup looking comparatively stronger).\n"
        "3. List the strongest risk factors as bullet points under a "
        "\"Risk factors:\" heading (facts that point toward it looking "
        "comparatively weaker or riskier).\n\n"
        f"{_NO_ADVICE_RULES}\n\n"
        "If a section below is empty, say coverage is limited there rather "
        "than inventing detail — an empty section is not itself a risk "
        "factor or a supporting factor, it's just missing data.\n\n"
        f"Latest close: {latest_close if latest_close is not None else 'unavailable'}\n\n"
        f"Key ratios:\n{ratio_lines or '(none available)'}\n\n"
        f"Technicals:\n{technical_lines or '(none available)'}\n\n"
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
    # Same function the score itself is built from (see its docstring) —
    # the summary's "supporting/risk factors" and the Opportunity Score's
    # component breakdown read from one shared set of numbers, not two
    # separately-computed views of the same company that could disagree.
    inputs = gather_score_inputs(db, asset)

    current_hash = _source_hash(news, ratios, inputs, latest_close)
    existing = get_cached_summary(db, asset)
    if existing is not None and not force and existing.source_hash == current_hash:
        return existing

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ProviderError("gemini_summary", "GEMINI_API_KEY not configured")

    prompt = _build_prompt(asset, ratios, news, inputs, latest_close)
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
