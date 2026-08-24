"""Market-agnostic value objects returned by providers.

These are plain, immutable data — never ORM models. Providers normalize
whatever shape their upstream API returns into these types, so engines and
services never see provider-specific JSON (architecture.md §F).
"""

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AssetRef:
    """A lightweight, provider-agnostic pointer to an instrument."""

    symbol: str
    exchange: str
    market: str = "IN"
    name: str | None = None
    isin: str | None = None


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar (as-reported, not corporate-action-adjusted)."""

    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None = None
    delivery_qty: int | None = None
    delivery_pct: float | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    """A live/latest price snapshot.

    `previous_close` rides along because every provider that can give an LTP
    gives it in the same payload, and a price with no reference point is
    close to useless on screen — deriving the day's change from stored EOD
    bars instead would silently go wrong on exactly the days that matter
    (a bar not yet ingested, or a corporate action between the two).

    `market_state` is the provider's own word for whether the session is
    live (e.g. "REGULAR", "CLOSED", "PRE", "POST"). Carried verbatim rather
    than normalised to a bool: "is the market open" is a question about a
    specific exchange's calendar and holidays, and the provider already
    knows the answer authoritatively — recomputing it from a hardcoded
    09:15–15:30 IST window would be wrong on every NSE holiday.
    """

    asset: AssetRef
    ltp: float
    as_of: dt.datetime
    previous_close: float | None = None
    market_state: str | None = None

    # The session's OHLCV so far. Enough to draw the forming candle without
    # a second request, since the same payload already carries it. Kept
    # separate from `Bar` deliberately: a Bar is a completed session that
    # has been ingested and is safe to persist and compute indicators on,
    # whereas these values are provisional and change until the close.
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    day_volume: int | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    """A split/bonus/dividend/rights event, as reported by a provider."""

    type: str
    ex_date: dt.date
    ratio: float | None = None
    amount: float | None = None


@dataclass(frozen=True, slots=True)
class Statements:
    """Line items for one reporting period. Values are flat — no nested schema."""

    asset: AssetRef
    period_type: str  # "FY" | "Q"
    period_end: dt.date
    statement_type: str  # "income" | "balance_sheet" | "cash_flow"
    line_items: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Ratios:
    """Derived financial ratios for an asset, keyed by ratio name (e.g. "roe", "roce")."""

    asset: AssetRef
    as_of: dt.date
    values: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Article:
    """A single news item, already deduplication-ready via `dedup_hash`."""

    url: str
    source: str
    published_at: dt.datetime
    title: str
    dedup_hash: str
    summary: str | None = None
    asset: AssetRef | None = None


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """Descriptive company metadata (not financials)."""

    asset: AssetRef
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
