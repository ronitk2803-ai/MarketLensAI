"""Unit tests for the prompt-building and cache-fingerprint logic in
company_summary.py. No DB/network fixtures needed — `_build_prompt` and
`_source_hash` are pure functions of the dataclasses/lists passed in, so
constructing those directly (not persisting them) is enough."""

import datetime as dt

from app.db.models import FinancialMetric, NewsArticle
from app.domain.models import AssetRef
from app.engines.scoring.base import ScoreInputs
from app.services.company_summary import _build_prompt, _source_hash

ASSET = AssetRef(symbol="ZZAI1", exchange="NSE", market="IN")


def _asset_row() -> object:
    # _build_prompt only reads .name/.symbol; a bare object with those
    # attributes is enough and avoids needing a DB-backed Asset row.
    class _A:
        name = "Test AI Co"
        symbol = "ZZAI1"

    return _A()


def _ratio(metric: str, value: float) -> FinancialMetric:
    return FinancialMetric(
        asset_id=1, metric=metric, value=value, source="yfinance_fundamentals", confidence="low"
    )


def _article(title: str, dedup_hash: str) -> NewsArticle:
    return NewsArticle(
        asset_id=1,
        url=f"https://example.com/{dedup_hash}",
        source="test",
        published_at=dt.datetime.now(dt.UTC),
        title=title,
        dedup_hash=dedup_hash,
    )


FULL_INPUTS = ScoreInputs(
    rsi14=33.7,
    drawdown_pct=-17.2,
    debt_to_equity=642.52,
    gross_margins=0.985,
    revenue_growth=0.145,
    earnings_growth=0.099,
    price_to_book=0.65,
    relative_volume=2.4,
    delivery_pct=61.3,
)


def test_prompt_includes_the_no_advice_rules() -> None:
    prompt = _build_prompt(_asset_row(), [], [], FULL_INPUTS, 491.4)

    assert "Do not recommend buying, selling, or holding" in prompt
    assert "Do not suggest a time horizon" in prompt
    assert "good or bad time to invest" in prompt


def test_prompt_asks_for_supporting_and_risk_factor_sections() -> None:
    prompt = _build_prompt(_asset_row(), [], [], FULL_INPUTS, 491.4)

    assert "Supporting factors:" in prompt
    assert "Risk factors:" in prompt


def test_prompt_includes_technicals_and_volume() -> None:
    prompt = _build_prompt(_asset_row(), [], [], FULL_INPUTS, 491.4)

    assert "RSI (14): 33.7" in prompt
    assert "Drawdown from recent peak: -17.2%" in prompt
    assert "Volume vs its 20-day average: 2.4x" in prompt
    assert "Delivery percentage: 61.3%" in prompt


def test_prompt_omits_missing_technicals_rather_than_showing_none() -> None:
    sparse = ScoreInputs(rsi14=33.7)  # everything else None

    prompt = _build_prompt(_asset_row(), [], [], sparse, 491.4)

    assert "RSI (14): 33.7" in prompt
    assert "None" not in prompt
    assert "Drawdown" not in prompt
    assert "Volume vs" not in prompt


def test_prompt_says_limited_coverage_when_everything_is_missing() -> None:
    empty = ScoreInputs()

    prompt = _build_prompt(_asset_row(), [], [], empty, None)

    assert "(none available)" in prompt  # ratios and technicals sections
    assert "(no recent news)" in prompt
    assert "unavailable" in prompt  # latest close


def test_source_hash_changes_when_rsi_changes() -> None:
    """Regression test: technicals weren't in the fingerprint before, so
    RSI crossing into oversold territory wouldn't have invalidated a cached
    summary — the same fundamentals+news fingerprint, but the prompt (and
    what the model should say about it) had changed underneath it."""
    ratios = [_ratio("debtToEquity", 36.65)]
    news: list[NewsArticle] = []

    hash_before = _source_hash(news, ratios, ScoreInputs(rsi14=65.0), 1300.0)
    hash_after = _source_hash(news, ratios, ScoreInputs(rsi14=28.0), 1300.0)

    assert hash_before != hash_after


def test_source_hash_changes_when_relative_volume_changes() -> None:
    ratios: list[FinancialMetric] = []
    news: list[NewsArticle] = []

    hash_before = _source_hash(news, ratios, ScoreInputs(relative_volume=1.0), 1300.0)
    hash_after = _source_hash(news, ratios, ScoreInputs(relative_volume=4.5), 1300.0)

    assert hash_before != hash_after


def test_source_hash_is_stable_for_identical_inputs() -> None:
    ratios = [_ratio("priceToBook", 1.97)]
    news = [_article("Some headline", "hash-a")]

    first = _source_hash(news, ratios, FULL_INPUTS, 1300.0)
    second = _source_hash(news, ratios, FULL_INPUTS, 1300.0)

    assert first == second
