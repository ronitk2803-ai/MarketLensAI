"""Market-agnostic instrument layer + price spine.

Schema per architecture/claude/Build_plan.md §C. India is a *value*
(`market="IN"`), never a code branch — keeps the door open for US/MF/ETF/
crypto later without a rewrite.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Asset(Base):
    """A tradable instrument. Market-agnostic: `market`/`asset_class` are data, not code."""

    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("market", "exchange", "symbol", name="uq_asset_market_exchange_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(index=True)
    exchange: Mapped[str]
    market: Mapped[str] = mapped_column(default="IN")
    asset_class: Mapped[str] = mapped_column(default="EQUITY")
    currency: Mapped[str] = mapped_column(default="INR")
    isin: Mapped[str | None] = mapped_column(unique=True)
    name: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument_maps: Mapped[list["InstrumentMap"]] = relationship(back_populates="asset")
    company: Mapped["Company | None"] = relationship(back_populates="asset")


class InstrumentMap(Base):
    """Maps an `Asset` to a provider's own instrument identifier (e.g. Upstox `instrument_key`)."""

    __tablename__ = "instrument_map"
    __table_args__ = (
        UniqueConstraint("provider", "provider_instrument_key", name="uq_instrument_map_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    provider: Mapped[str]
    provider_instrument_key: Mapped[str]

    asset: Mapped["Asset"] = relationship(back_populates="instrument_maps")


class Industry(Base):
    """Taxonomy entry; `score_profile_key` selects which weighting profile applies (§M)."""

    __tablename__ = "industry"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    score_profile_key: Mapped[str] = mapped_column(default="default")


class Company(Base):
    """1:1 extension of `Asset` with sector/industry classification and profile text."""

    __tablename__ = "company"

    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    sector: Mapped[str | None]
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industry.id"))
    description: Mapped[str | None]
    mgmt_notes: Mapped[str | None]

    asset: Mapped["Asset"] = relationship(back_populates="company")
    industry: Mapped["Industry | None"] = relationship()


class PriceOHLCV(Base):
    """Full daily bar (D-006): decision to store OHLCV + OI + delivery% for all history.

    Raw as-reported values; corporate-action adjustment is applied by the indicator
    engine at read time from `CorporateAction`, not by mutating rows here.
    """

    __tablename__ = "price_ohlcv"
    __table_args__ = (Index("ix_price_ohlcv_date", "date"),)

    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    oi: Mapped[int | None] = mapped_column(BigInteger)
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    delivery_qty: Mapped[int | None] = mapped_column(BigInteger)
    delivery_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    source: Mapped[str]
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProviderFetchLog(Base):
    """Every external provider call, for caching/freshness + provider-health monitoring (§X.5)."""

    __tablename__ = "provider_fetch_log"
    __table_args__ = (Index("ix_provider_fetch_log_provider_fetched_at", "provider", "fetched_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str]
    endpoint: Mapped[str]
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("asset.id"), index=True)
    status: Mapped[str]  # "success" | "error"
    latency_ms: Mapped[int | None]
    ttl_seconds: Mapped[int | None]
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FinancialStatement(Base):
    """Best-effort statement line items (Build_plan.md §7/§C, D-002): partial +
    confidence-flagged, never fabricated. `confidence` is per-row, not
    per-asset, since coverage is uneven line-item by line-item."""

    __tablename__ = "financial_statement"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "period_type",
            "period_end",
            "statement_type",
            "line_item",
            name="uq_financial_statement_line",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    period_type: Mapped[str]  # "FY" | "Q"
    period_end: Mapped[dt.date] = mapped_column(Date)
    statement_type: Mapped[str]  # "income" | "balance_sheet" | "cash_flow"
    line_item: Mapped[str]
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    source: Mapped[str]
    confidence: Mapped[str]  # "high" | "low"
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialMetric(Base):
    """Best-effort derived ratios (ROE/ROCE/D-E/margins/growth). Latest-known-
    value cache, not a historical series — upserted per (asset, metric)."""

    __tablename__ = "financial_metric"
    __table_args__ = (
        UniqueConstraint("asset_id", "metric", name="uq_financial_metric_asset_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    metric: Mapped[str]
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    source: Mapped[str]
    confidence: Mapped[str]  # "high" | "low"
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorporateAction(Base):
    """Splits/bonus/dividends/rights — drives price adjustment (correctness-critical, D-007)."""

    __tablename__ = "corporate_action"
    __table_args__ = (Index("ix_corporate_action_asset_ex_date", "asset_id", "ex_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    type: Mapped[str]
    ex_date: Mapped[dt.date] = mapped_column(Date)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source: Mapped[str]
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NewsArticle(Base):
    """Deduplicated news (Build_plan.md §8/§14). `sentiment`/`event_type`/
    `relevance` are P1/P2 classification enrichments (FinBERT/LLM) — left
    NULL for now rather than guessed; this table only does fetch + dedup."""

    __tablename__ = "news_article"
    __table_args__ = (UniqueConstraint("dedup_hash", name="uq_news_article_dedup_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("asset.id"), index=True)
    url: Mapped[str]
    source: Mapped[str]
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str]
    summary: Mapped[str | None]
    sentiment: Mapped[str | None]
    event_type: Mapped[str | None]
    relevance: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    dedup_hash: Mapped[str]
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CompanyAiSummary(Base):
    """Cached AI-generated narrative summary (news + fundamentals + price in
    one paragraph). Generated on user demand via a button click, not on a
    schedule (app/services/company_summary.py) — one row per asset, a fresh
    generation overwrites rather than accumulating history. `source_hash`
    fingerprints the inputs a generation was based on, so a click when
    nothing material changed since the last one reuses this row instead of
    spending another (free-tier, rate-limited) LLM call."""

    __tablename__ = "company_ai_summary"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), unique=True, index=True)
    summary: Mapped[str]
    source_hash: Mapped[str]
    model: Mapped[str]
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScoreProfile(Base):
    """Weight configuration for the scoring engine (Build_plan.md §L/§M):
    "weights are versioned configuration, never code constants." Only a
    "default" profile is seeded — industry-specific profiles are P2 (see
    app/engines/scoring/registry.py for why real ones aren't faked yet).
    `active` lets a new version supersede an old one without deleting the
    historical record a past Score row was computed against."""

    __tablename__ = "score_profile"
    __table_args__ = (
        UniqueConstraint("industry_code", "version", name="uq_score_profile_industry_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_code: Mapped[str] = mapped_column(default="default")
    version: Mapped[int] = mapped_column(default=1)
    weights: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Score(Base):
    """Append-only per Build_plan.md §L ("snapshot inputs every run" ->
    future backtesting needs the historical record, not just latest-wins).
    The service only computes a new row once per day (EOD data doesn't
    change intraday) rather than on every request."""

    __tablename__ = "score"
    __table_args__ = (Index("ix_score_asset_as_of", "asset_id", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("score_profile.id"))
    value: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    coverage: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    confidence: Mapped[str]  # "high" | "low"
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoreComponent(Base):
    """Per-component breakdown for one `Score` row — the input snapshot
    that makes the score explainable and, later, backtestable."""

    __tablename__ = "score_component"

    id: Mapped[int] = mapped_column(primary_key=True)
    score_id: Mapped[int] = mapped_column(ForeignKey("score.id"), index=True)
    component: Mapped[str]
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    contribution: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
