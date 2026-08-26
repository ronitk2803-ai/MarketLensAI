"""Tests for company_summary.py.

The prompt-building and cache-fingerprint tests need no DB/network
fixtures — `_build_prompt` and `_source_hash` are pure functions of the
dataclasses/lists passed in, so constructing those directly (not
persisting them) is enough. The provider-health and cooldown tests at the
bottom are DB-backed, since the whole point of those is what gets written
to provider_fetch_log."""

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import Asset, FinancialMetric, NewsArticle, ProviderFetchLog
from app.domain.models import AssetRef
from app.engines.scoring.base import ScoreInputs
from app.providers.errors import ProviderError
from app.services import company_summary as cs
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


# --- Provider-health logging and the failure cooldown (DB-backed) ---
#
# The reason a completely dead LLM went unnoticed for days: the one
# provider that never wrote to provider_fetch_log was the one that broke.
# These pin that it now does, and that a broken provider isn't re-probed on
# every click.


# generate_summary commits on the failure path so the provider-health row
# survives get_db's rollback — which means an asset created by a
# failure-path test is committed too, and the usual rollback-only `db`
# fixture can't undo it. Same situation, and same remedy, as
# test_daily_ingestion.py's teardown.
_COMMITTING_TEST_SYMBOLS = ("ZZAIFAIL", "ZZAICOMMIT")


@pytest.fixture(autouse=True)
def _cleanup_committed_rows(db: Session):
    yield
    db.rollback()
    asset_ids = [
        row[0]
        for row in db.query(Asset.id)
        .filter(Asset.symbol.in_(_COMMITTING_TEST_SYMBOLS))
        .all()
    ]
    if asset_ids:
        db.query(ProviderFetchLog).filter(
            ProviderFetchLog.asset_id.in_(asset_ids)
        ).delete(synchronize_session=False)
        db.query(Asset).filter(Asset.id.in_(asset_ids)).delete(synchronize_session=False)
        db.commit()


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _stub_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything generate_summary gathers before it reaches the provider."""
    monkeypatch.setattr(cs, "get_or_fetch_ratios", lambda db, asset: [])
    monkeypatch.setattr(cs, "get_or_fetch_news", lambda db, asset: [])
    monkeypatch.setattr(cs, "get_adjusted_bars", lambda db, asset, lookback_days: ([], "test"))
    monkeypatch.setattr(cs, "gather_score_inputs", lambda db, asset: ScoreInputs())

    class _Settings:
        gemini_api_key = "test-key"

    monkeypatch.setattr(cs, "get_settings", lambda: _Settings())


def _fetch_rows(db: Session, asset_id: int) -> list[ProviderFetchLog]:
    return (
        db.query(ProviderFetchLog)
        .filter_by(asset_id=asset_id, endpoint=cs.AI_SUMMARY_ENDPOINT)
        .all()
    )


def test_a_successful_generation_is_recorded_as_provider_health(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _asset(db, "ZZAIOK")
    _stub_inputs(monkeypatch)
    monkeypatch.setattr(
        cs.GeminiSummaryProvider, "generate", lambda self, prompt: "a summary"
    )

    cs.generate_summary(db, asset)

    rows = _fetch_rows(db, asset.id)
    assert [r.status for r in rows] == ["success"]
    assert rows[0].provider == "gemini_summary"


def test_a_failed_generation_is_recorded_and_the_error_still_propagates(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _asset(db, "ZZAIFAIL")
    _stub_inputs(monkeypatch)

    def boom(self: object, prompt: str) -> str:
        raise ProviderError("gemini_summary", "request failed: timed out", retryable=True)

    monkeypatch.setattr(cs.GeminiSummaryProvider, "generate", boom)

    with pytest.raises(ProviderError, match="request failed"):
        cs.generate_summary(db, asset)

    assert [r.status for r in _fetch_rows(db, asset.id)] == ["error"]


def test_a_recent_failure_short_circuits_without_calling_the_provider(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken provider costs the full retry budget per call. Without this
    the cost is paid again on every single click."""
    asset = _asset(db, "ZZAICOOL")
    _stub_inputs(monkeypatch)
    db.add(
        ProviderFetchLog(
            provider="gemini_summary",
            endpoint=cs.AI_SUMMARY_ENDPOINT,
            asset_id=asset.id,
            status="error",
        )
    )
    db.flush()

    calls = {"n": 0}

    def counted(self: object, prompt: str) -> str:
        calls["n"] += 1
        return "a summary"

    monkeypatch.setattr(cs.GeminiSummaryProvider, "generate", counted)

    with pytest.raises(ProviderError, match="try again"):
        cs.generate_summary(db, asset)

    assert calls["n"] == 0  # never reached the network


def test_an_old_failure_does_not_suppress_a_fresh_attempt(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = _asset(db, "ZZAIOLD")
    _stub_inputs(monkeypatch)
    stale = dt.datetime.now(dt.UTC) - cs.GENERATION_RETRY_COOLDOWN - dt.timedelta(minutes=1)
    db.add(
        ProviderFetchLog(
            provider="gemini_summary",
            endpoint=cs.AI_SUMMARY_ENDPOINT,
            asset_id=asset.id,
            status="error",
            fetched_at=stale,
        )
    )
    db.flush()
    monkeypatch.setattr(
        cs.GeminiSummaryProvider, "generate", lambda self, prompt: "a summary"
    )

    row = cs.generate_summary(db, asset)

    assert row.summary == "a summary"


def test_a_previous_success_never_suppresses_a_later_attempt(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cooldown is keyed on failure only — a successful generation is
    already short-circuited by source_hash, so suppressing on success would
    block a legitimate regeneration after the data changed."""
    asset = _asset(db, "ZZAIPREV")
    _stub_inputs(monkeypatch)
    db.add(
        ProviderFetchLog(
            provider="gemini_summary",
            endpoint=cs.AI_SUMMARY_ENDPOINT,
            asset_id=asset.id,
            status="success",
        )
    )
    db.flush()
    monkeypatch.setattr(
        cs.GeminiSummaryProvider, "generate", lambda self, prompt: "fresh"
    )

    assert cs.generate_summary(db, asset).summary == "fresh"


def test_the_failure_record_survives_the_request_rollback(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug the tests above missed. They use the rollback-scoped `db`
    fixture and so never exercise get_db's exception path — but in a real
    request the ProviderError propagates, get_db rolls back, and a merely
    flushed log row disappears with it. Both the provider-health record and
    the cooldown that reads it would then silently never exist. Asserted
    from a *separate* session, which is the only way to tell a committed
    row from a flushed one."""
    from app.db.session import SessionLocal

    asset = _asset(db, "ZZAICOMMIT")
    db.commit()  # the asset has to be visible to the other session too
    _stub_inputs(monkeypatch)

    def boom(self: object, prompt: str) -> str:
        raise ProviderError("gemini_summary", "request failed: timed out", retryable=True)

    monkeypatch.setattr(cs.GeminiSummaryProvider, "generate", boom)

    with pytest.raises(ProviderError):
        cs.generate_summary(db, asset)

    observer = SessionLocal()
    try:
        survived = (
            observer.query(ProviderFetchLog)
            .filter_by(asset_id=asset.id, endpoint=cs.AI_SUMMARY_ENDPOINT)
            .all()
        )
    finally:
        observer.close()
    assert [r.status for r in survived] == ["error"]
