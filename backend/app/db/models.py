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
    text,
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


class SectorIndexPe(Base):
    """NSE's own daily sectoral-index P/E/P/B/dividend-yield (one row per
    Nifty index NSE publishes it for, e.g. "Nifty Financial Services") —
    the authoritative "what's this sector trading at" figure, computed by
    NSE across the index's full constituent set. Latest-known-value cache,
    like FinancialMetric: refreshed once daily, no history kept, because
    the comparison only ever needs "today's" figure.

    See app/services/sector_index.py's INDUSTRY_TO_NIFTY_INDEX for the
    (partial — not every app/db/models.py Industry has an official Nifty
    sectoral index) mapping from this app's own industry taxonomy to these
    rows."""

    __tablename__ = "sector_index_pe"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_name: Mapped[str] = mapped_column(unique=True)
    pe: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    pb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    div_yield: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    index_date: Mapped[dt.date]
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
    "weights are versioned configuration, never code constants."

    `industry_code` is matched against `Industry.score_profile_key` (not
    `Industry.code`) so several industries can share one profile. Profiles
    differ by which components apply, not just how they're weighted — see
    app/engines/scoring/registry.py for the evidence bar a profile has to
    clear before being seeded, and why only "default" and "financials"
    currently clear it.

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

    # Which weights produced this row. Kept resolvable (rather than just an
    # id) because profiles apply different component sets, so a score is
    # only interpretable alongside the profile that computed it.
    profile: Mapped["ScoreProfile"] = relationship()


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


class AppUser(Base):
    """User layer (Build_plan.md §C/§O, P1): the account everything else in
    that layer — portfolio, a real watchlist, thesis tracker — gets gated
    behind once it's introduced. Not named `user`: that's a reserved word
    in Postgres, and SQLAlchemy would only silently quote around it.

    `hashed_password` is an Argon2 hash (app/services/auth.py), never the
    raw password — same "never store the sensitive thing directly" rule
    RefreshToken.token_hash below follows for tokens. It is NULLABLE
    because an account created through Google sign-in has no password at
    all; a sentinel "unusable hash" string would have worked too, but a
    real NULL is the honest representation and lets `has_password` be a
    plain IS NULL check rather than a comparison against a magic value.
    Every read path must therefore handle None — see
    app/services/auth.py's authenticate_user.

    `email` is a plain String with a unique btree, NOT citext, and
    lowercasing happens in application code (create_user,
    authenticate_user, and the Google link path). Any new write path has
    to `.strip().lower()` itself or it will happily insert a second row
    for the same address in different case."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(default=None)
    # When the address was proven reachable, not merely whether — a
    # timestamp answers "how long has this account been verified?" for
    # free, and NULL is an unambiguous "never". Existing accounts were
    # backfilled to their created_at when this column was added, so the
    # verified gate only ever applies to signups after that migration.
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Google's `sub` claim: stable for the life of the Google account and
    # unchanged if the user renames their Gmail address, which is exactly
    # why the link is keyed on this rather than on email.
    google_sub: Mapped[str | None] = mapped_column(unique=True, default=None)
    # What to call this person in the UI. NULL for every password signup —
    # the register form doesn't ask, and deriving one from the local part of
    # the address ("ronit.k2803" -> "Ronit") is exactly the fabrication
    # SUMMARISER §7 rule 1 forbids. Read paths fall back to `email`, which is
    # honest rather than invented. Populated today only from Google's
    # `profile` scope; not unique, not indexed — two people may share a name
    # and nothing looks an account up by it.
    display_name: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefreshToken(Base):
    """One row per issued refresh token, so a token can actually be revoked
    (logout) rather than just expiring on its own — a stateless JWT alone
    can't do that. `token_hash` is a SHA-256 hash of the raw token, not the
    token itself: a DB leak alone must not hand out usable credentials, the
    same reasoning as password hashing.

    Rotated on every use (app/services/auth.py's rotate_refresh_token):
    each refresh revokes this row and issues a fresh one, so a leaked
    refresh token has a shrinking window before its next legitimate use
    invalidates it."""

    __tablename__ = "refresh_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["AppUser"] = relationship()


class WatchlistItem(Base):
    """One account's watchlist — deliberately just a flat (user, asset) set
    rather than the `watchlist` + `watchlist_item` pair Build_plan.md §C
    sketches (which anticipates multiple *named* lists, a P2 idea nothing
    today needs): a single implicit list per user is the whole feature
    that was actually asked for, and splitting this into two tables later
    if named lists ever get built is a small additive migration, not a
    rewrite.

    `unique(user_id, asset_id)` doubles as "add" being naturally idempotent
    at the DB level — the service layer still checks first so it can tell
    the caller whether anything changed, but the constraint is the real
    backstop against a race duplicating a row."""

    __tablename__ = "watchlist_item"
    __table_args__ = (UniqueConstraint("user_id", "asset_id", name="uq_watchlist_item_user_asset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    added_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Thesis(Base):
    """An investor's stated conviction on one asset, plus the conditions
    (ThesisTrigger) that would prove it wrong — Build_plan.md §X.1, the
    "build *or challenge* conviction" feature. `stance`/`status` are plain
    strings validated by the API layer's Pydantic models (Literal[...]),
    not a DB-level Enum — matching every other enum-shaped column in this
    file (e.g. FinancialMetric.confidence).

    `status` has four states, reconciling an inconsistency between two
    bullets in the spec itself (Outputs says active/challenged/invalidated,
    Data says active/invalidated/closed) by taking the union: "active" (no
    trigger has fired yet), "challenged" (one has — set once, automatically,
    by the eval job; never reverts), "invalidated"/"closed" (user-set only,
    via PUT, meaning the eval job stops evaluating this thesis's triggers).
    """

    __tablename__ = "thesis"
    __table_args__ = (Index("ix_thesis_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    title: Mapped[str]
    body: Mapped[str]
    stance: Mapped[str]  # "bull" | "bear" | "neutral"
    conviction: Mapped[int]  # 1-5, enforced by the API layer's Pydantic model
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped["Asset"] = relationship()
    triggers: Mapped[list["ThesisTrigger"]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )


class ThesisTrigger(Base):
    """One invalidation condition (`metric operator threshold`, e.g.
    debt_to_equity > 1.5) — see app/services/metric_registry.py for the
    registry of resolvable `metric` keys and app/engines/thesis/base.py
    for how `operator`/`threshold` get evaluated against an observed value.

    Immutable once created — deliberately no update path. The spec's own
    API list (Build_plan.md §X.1) never mentions a trigger-editing
    endpoint, and this codebase never sets `ondelete=` on any FK (a
    delete-and-recreate "edit" would either hard-fail once a trigger has
    ever fired, since ThesisEvent.trigger_id references it, or — if
    cascade were added for that case — silently destroy the append-only
    event history the feature exists to preserve). A thesis's triggers
    only ever disappear together, by deleting the whole thesis.

    Dropped the spec's `direction` column: `operator` (gt/lt/gte/lte/eq)
    already fully determines evaluation semantics, and nothing in the spec
    text assigns `direction` independent meaning beyond that.

    `currently_breached` isn't in the spec's schema line either, but is
    necessary: without it, a trigger that stays breached for months would
    write a new ThesisEvent on every single daily eval, burying the one
    moment that actually mattered (when it first broke). The eval job only
    writes an event on the false -> true transition.
    """

    __tablename__ = "thesis_trigger"

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_id: Mapped[int] = mapped_column(
        ForeignKey("thesis.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str]
    operator: Mapped[str]  # "gt" | "lt" | "gte" | "lte" | "eq"
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    description: Mapped[str | None]
    currently_breached: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    thesis: Mapped["Thesis"] = relationship(back_populates="triggers")


class ThesisEvent(Base):
    """Append-only log of when a trigger fired (a false -> true breach
    transition — see ThesisTrigger.currently_breached), with the value
    observed at that moment. This is the historical record the whole
    feature is for, so nothing here is ever updated or deleted except as
    part of deleting the entire parent thesis (both FKs cascade)."""

    __tablename__ = "thesis_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_id: Mapped[int] = mapped_column(
        ForeignKey("thesis.id", ondelete="CASCADE"), index=True
    )
    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("thesis_trigger.id", ondelete="CASCADE"), index=True
    )
    fired_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    note: Mapped[str | None]

    trigger: Mapped["ThesisTrigger"] = relationship()


class Holding(Base):
    """One "lot" of a user's position in one asset, tagged with which
    broker it came from — deliberately not a single flat (user, asset)
    row, and not the `portfolio` + `holding` pair Build_plan.md §C
    sketches either. A user can hold the same stock across multiple demat
    accounts (e.g. Zerodha AND Upstox) plus a hand-entered position no
    broker export knows about; app/services/portfolio.py's list_holdings
    sums every lot for an asset into one consolidated view (weighted-
    average cost basis), so this table stores the underlying lots, not
    the consolidated total.

    Only `quantity`/`avg_cost` are stored per lot — current price, market
    value, and P&L are computed live on every read, the same "recompute
    from stored EOD data on every request, never cache a number that can
    go stale" discipline watchlist.py already applies to quotes.

    `quantity` is Numeric rather than an integer count: NSE equity
    positions are whole shares in practice, but this app's instrument
    layer is deliberately market-agnostic (US/MF/ETF/crypto per §C) and
    corporate-action-driven fractional entitlements are real, so an
    integer would be a constraint with no corresponding benefit.

    `broker` ("manual" | "zerodha" | "upstox") is why a CSV import can't
    silently destroy a hand-entered holding, or a different broker's
    holding, for the same asset: import only ever replaces the lots it
    previously created for that exact broker
    (app/services/portfolio.py's import_holdings_file), never another
    broker's or a manual lot.

    `unique(user_id, asset_id, broker)`: a user holds at most one lot per
    asset *per broker*. Unlike WatchlistItem, adding an already-held
    (asset, broker) pair again is NOT a no-op — it's how a position
    change (or a re-import) is recorded, so this constraint backstops
    upsert-in-place within one broker, not idempotent no-op-add."""

    __tablename__ = "holding"
    __table_args__ = (
        UniqueConstraint("user_id", "asset_id", "broker", name="uq_holding_user_asset_broker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    broker: Mapped[str]  # "manual" | "zerodha" | "upstox"
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    asset: Mapped["Asset"] = relationship()


class Alert(Base):
    """One thing worth telling a user about, generated by the daily job
    (Build_plan.md §S step 24). Two sources: a thesis trigger firing —
    which Build_plan.md §X.1 always intended to "emit an alert" but
    deferred to P2 — and system-chosen signals on watchlisted stocks
    (Screener.md §16's list, kept deliberately short per its own "do not
    implement unnecessary alert complexity in V1").

    A separate table rather than a flag on ThesisEvent: that table
    declares itself append-only and immutable, so a mutable `read_at`
    there would contradict its own contract. This one is explicitly
    mutable — `read_at` is the whole point of an inbox.

    `dedup_key` + unique(user_id, dedup_key) is what makes generation
    idempotent, and it is keyed off the *bar date* the signal came from,
    never today's date. The scheduler runs seven days a week (no
    day_of_week in app/main.py's cron), so a today-keyed alert would
    re-announce Friday's 6% drop again on Saturday, on Sunday, and on
    every NSE holiday, off a bar that never changed.

    Rows are never deleted to acknowledge them — the dedup row IS the
    memory of having alerted, so deleting it would let the next night's
    run regenerate the same alert. Read alerts are swept after 90 days
    instead (app/services/alerts.py), so this doesn't grow without bound
    (product_principles.md #9).

    `as_of` is the bar date the signal was computed from, not when the
    row was written. These are end-of-day numbers surfaced hours after
    the close, and this app's own footer promises every figure carries
    its own timestamp."""

    __tablename__ = "alert"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_alert_user_dedup_key"),
        # Serves the unread count that GET /auth/me returns on every page
        # render, so the header bell costs an index probe rather than a
        # scan of everything the user has ever been told.
        Index(
            "ix_alert_user_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    # CASCADE because tests (and a real delisting cleanup) delete assets;
    # an alert about a stock that no longer exists has nothing to say.
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), index=True
    )
    # "thesis_challenged" | "price_drop" | "price_surge" | "unusual_volume"
    # | "week52_high" | "week52_low"
    kind: Mapped[str]
    title: Mapped[str]
    body: Mapped[str | None]
    dedup_key: Mapped[str]
    thesis_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("thesis_event.id", ondelete="CASCADE")
    )
    as_of: Mapped[dt.date] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped["Asset"] = relationship()


class AuthCode(Base):
    """A short-lived numeric code proving someone controls an email address.

    One table for both purposes rather than two, because they differ in
    nothing but the `purpose` string: same columns, same throttle, same
    expiry, same sweep. `purpose` follows Alert.kind's precedent — a plain
    string documented by its type alias, not a DB enum, so adding a third
    kind later is a code change rather than a migration.

    `code_hash` is HMAC-SHA256 keyed on the app's JWT secret, NOT the bare
    SHA-256 that RefreshToken.token_hash uses, and the difference matters.
    A refresh token is 48 bytes of `secrets.token_urlsafe` — unsearchable,
    so a plain digest leaks nothing. A 6-digit code is about 20 bits; a
    bare digest of one is reversed from a stolen database instantly by
    hashing all 10^6 candidates. Keying on a secret that lives in the
    environment rather than in Postgres closes that completely. Argon2
    would only have made the 10^6 search slow, and would have put a 64 MiB
    allocation on an unauthenticated endpoint.

    `attempts` and the short expiry are what stop *online* guessing, and
    they are load-bearing rather than defence in depth — see
    app/services/auth_codes.py, where the increment is committed before the
    error is raised precisely so a rolled-back request cannot erase it.
    """

    __tablename__ = "auth_code"
    __table_args__ = (
        # At most one live code per purpose per user, enforced rather than
        # merely intended: several live codes would multiply the guess
        # surface while sharing one attempt budget. Partial-unique mirrors
        # Alert's ix_alert_user_unread.
        Index(
            "uq_auth_code_live",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str]  # "verify_email" | "password_reset"
    code_hash: Mapped[str]
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    # Set both when the code is used and when it is retired unused — a
    # superseded code, one whose attempts ran out, or one whose email
    # failed to send. "Consumed" here means "no longer usable", not
    # "successfully used".
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
