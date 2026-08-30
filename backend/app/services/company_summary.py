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

import datetime as dt
import hashlib
import time

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Asset,
    CompanyAiSummary,
    FinancialMetric,
    NewsArticle,
    ProviderFetchLog,
)
from app.engines.scoring.base import ScoreInputs
from app.providers.ai.gemini_summary import DEFAULT_MODEL, GeminiSummaryProvider
from app.providers.errors import ProviderError
from app.providers.fetch_log import record_fetch
from app.services.adjusted_prices import get_adjusted_bars
from app.services.fundamentals import get_or_fetch_ratios
from app.services.indian_units import format_metric_for_prose
from app.services.news import get_or_fetch_news
from app.services.scoring import gather_score_inputs

SOURCE = "gemini_summary"
AI_SUMMARY_ENDPOINT = "ai_summary_generate"

# How long a failed generation suppresses further attempts for that asset.
# Long enough that a broken provider isn't re-probed on every click, short
# enough that a transient outage clears without anyone waiting it out.
GENERATION_RETRY_COOLDOWN = dt.timedelta(minutes=10)

# These two MUST stay equal. The hash decides whether a cached summary is
# still valid; the prompt decides what the model saw. If the prompt read
# more items than the hash covered, a change in the extra ones would alter
# the summary the model would write without invalidating the cached one,
# and the page would show a summary that no longer matches its own inputs.
_NEWS_FOR_PROMPT = 12
_NEWS_FOR_HASH = _NEWS_FOR_PROMPT


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
    # marketCap/sharesOutstanding/floatShares are pre-formatted into
    # Indian-convention prose (₹X lakh crore, X.XX crore shares) here, not
    # left for the model to convert itself — verified live: unguided, it
    # narrates a raw marketCap figure as "$1.6 trillion", correct
    # arithmetic but the wrong convention for an app entirely about
    # Indian equities. See app/services/indian_units.py's module
    # docstring for why this is a code concern, not a prompt-wording one.
    ratio_lines = "\n".join(
        f"- {r.metric}: {format_metric_for_prose(r.metric, float(r.value))}" for r in ratios
    )
    # Dated and attributed, not bare titles. get_or_fetch_news looks back 30
    # days, so an undated list mixes this morning's headline with one from
    # four weeks ago and the model has no way to tell them apart — it will
    # describe month-old news as if it just happened. The date is the whole
    # difference between "recent headlines" meaning something and not.
    news_lines = "\n".join(
        f"- {a.published_at.date()} ({a.source}): {a.title}"
        for a in news[:_NEWS_FOR_PROMPT]
    )
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
        "Headlines carry their publication date. Weight the recent ones "
        "more heavily, and when you refer to something from more than a "
        "week ago, say when it happened rather than implying it is "
        "current news.\n\n"
        "Market cap and share counts below are already given in Indian "
        "convention (lakh/crore) — use them exactly as given, never "
        "convert to million/billion/trillion.\n\n"
        f"Latest close: {latest_close if latest_close is not None else 'unavailable'}\n\n"
        f"Key ratios:\n{ratio_lines or '(none available)'}\n\n"
        f"Technicals:\n{technical_lines or '(none available)'}\n\n"
        f"Recent headlines, newest first (dates are when each was published; "
        f"today is {dt.date.today()}):\n{news_lines or '(no recent news)'}"
    )


def get_cached_summary(db: Session, asset: Asset) -> CompanyAiSummary | None:
    """Read-only — never generates. Safe to call on every page load."""
    return db.query(CompanyAiSummary).filter_by(asset_id=asset.id).one_or_none()


def _recently_failed(db: Session, asset_id: int) -> bool:
    """Whether the last generation attempt for this asset failed inside the
    cooldown. Mirrors prices.py's _recently_attempted, but keyed on failure
    only: a *successful* generation is already short-circuited by
    source_hash, so there's nothing to suppress there."""
    last = (
        db.query(ProviderFetchLog)
        .filter_by(asset_id=asset_id, endpoint=AI_SUMMARY_ENDPOINT)
        .order_by(ProviderFetchLog.fetched_at.desc())
        .first()
    )
    if last is None or last.status != "error":
        return False
    fetched_at = last.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - fetched_at) < GENERATION_RETRY_COOLDOWN


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
    if not settings.gemini_api_keys:
        raise ProviderError("gemini_summary", "GEMINI_API_KEY_1 not configured")

    # A provider that's down stays down for a while, and each failed call
    # costs the full retry budget. Without this, every click on a broken
    # provider pays that again — the same reasoning (and the same
    # ProviderFetchLog-backed mechanism) as prices.py's _recently_attempted.
    if _recently_failed(db, asset.id):
        raise ProviderError(
            "gemini_summary",
            "a recent generation for this company failed — try again in a few minutes",
            retryable=True,
        )

    prompt = _build_prompt(asset, ratios, news, inputs, latest_close)
    started_at = time.monotonic()
    try:
        text = GeminiSummaryProvider(settings.gemini_api_keys).generate(prompt)
    except ProviderError:
        # Logged before re-raising, so a dead provider is visible in
        # provider_fetch_log (Build_plan.md §X.5's whole purpose) instead of
        # only in whatever the user happened to see in the UI. This was the
        # actual reason a completely non-functional LLM went unnoticed: the
        # one provider that never recorded a fetch was the one that broke.
        record_fetch(
            db,
            provider="gemini_summary",
            endpoint=AI_SUMMARY_ENDPOINT,
            status="error",
            asset_id=asset.id,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
        # Committed here, not merely flushed, and this is the one place in
        # this service that commits. The exception about to be raised
        # reaches app/db/session.py's get_db, which rolls the request back
        # — so a flushed-only row would vanish along with it, and both the
        # provider-health record and the cooldown that depends on it would
        # silently never exist. Verified live: without this the second
        # click still paid the full retry budget.
        db.commit()
        raise
    record_fetch(
        db,
        provider="gemini_summary",
        endpoint=AI_SUMMARY_ENDPOINT,
        status="success",
        asset_id=asset.id,
        latency_ms=round((time.monotonic() - started_at) * 1000),
    )

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
