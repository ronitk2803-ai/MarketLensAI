"""A user's watchlist: which symbols are on it (this module, account-backed
as of P1 — see WatchlistItem) and what their quotes look like
(get_watchlist_quotes, unchanged since before accounts existed).

Quoting is deliberately stored-data-only, same discipline as
opportunities.py: a watchlist is refreshed on every page load, so fetching
live per symbol here would be the exact "N live API storms" pattern
Build_plan.md §K rules out for screens. It reads whatever daily_ingestion
has already landed.

Membership used to have no persistence at all — Build_plan.md §Q listed
"watchlist" as explicitly out of MVP scope because a real one needs
accounts, and the frontend kept the list in the browser (localStorage)
instead. Now that accounts exist (P1), it's a real per-user table.
"""

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import Asset, PriceOHLCV, WatchlistItem
from app.domain.models import Bar
from app.engines.adjustment import adjust_bars
from app.services.corporate_actions import get_stored_corporate_actions
from app.services.prices import row_to_bar

SPARK_SESSIONS = 30
_52_WEEK_CALENDAR_DAYS = 365


@dataclass(frozen=True, slots=True)
class RangeStat:
    high: float
    low: float
    # Where the latest close sits between low and high, 0.0..1.0. None when
    # high == low (a single bar, or a totally flat series) since the ratio
    # is undefined rather than meaningfully 0.
    position: float | None
    since: dt.date  # first bar this stat was actually computed over


@dataclass(frozen=True, slots=True)
class WatchlistQuote:
    symbol: str
    exchange: str
    name: str
    as_of: dt.date | None
    close: float | None
    # requested-N -> % change, keyed by the same ints the caller passed in.
    # A window with too little history to evaluate is simply absent, not 0
    # or null-filled — the "missing, not fabricated" rule (Build_plan.md §7)
    # applies here exactly like everywhere else in this codebase.
    deltas: dict[int, float] = field(default_factory=dict)
    all_time: RangeStat | None = None
    week_52: RangeStat | None = None
    spark: list[float] = field(default_factory=list)


def _load_all_adjusted_bars(db: Session, asset: Asset) -> list[Bar]:
    rows = (
        db.query(PriceOHLCV)
        .filter_by(asset_id=asset.id)
        .order_by(PriceOHLCV.date)
        .all()
    )
    raw_bars = [row_to_bar(r) for r in rows]
    actions = get_stored_corporate_actions(db, asset.id)
    return adjust_bars(raw_bars, actions)


def _range_stat(bars: list[Bar], *, latest_close: float) -> RangeStat | None:
    if not bars:
        return None
    high = max(b.high for b in bars)
    low = min(b.low for b in bars)
    position = (latest_close - low) / (high - low) if high > low else None
    return RangeStat(high=high, low=low, position=position, since=bars[0].date)


def get_watchlist_quotes(
    db: Session, symbols: list[str], *, delta_days: list[int]
) -> tuple[list[WatchlistQuote], list[str]]:
    """Returns (quotes, symbols with no matching active NSE asset)."""
    wanted = [s.strip().upper() for s in symbols if s.strip()]
    assets = {
        a.symbol: a
        for a in db.query(Asset).filter(
            Asset.symbol.in_(wanted), Asset.market == "IN", Asset.exchange == "NSE"
        )
    }

    quotes: list[WatchlistQuote] = []
    unknown: list[str] = []
    for symbol in wanted:
        asset = assets.get(symbol)
        if asset is None:
            unknown.append(symbol)
            continue

        bars = _load_all_adjusted_bars(db, asset)
        if not bars:
            quotes.append(
                WatchlistQuote(
                    symbol=symbol,
                    exchange=asset.exchange,
                    name=asset.name,
                    as_of=None,
                    close=None,
                )
            )
            continue

        latest = bars[-1]
        deltas: dict[int, float] = {}
        for n in delta_days:
            if n <= 0 or len(bars) <= n:
                continue
            anchor = bars[-(n + 1)].close
            if anchor:
                deltas[n] = (latest.close - anchor) / anchor * 100

        cutoff = latest.date - dt.timedelta(days=_52_WEEK_CALENDAR_DAYS)
        recent_bars = [b for b in bars if b.date >= cutoff]

        quotes.append(
            WatchlistQuote(
                symbol=symbol,
                exchange=asset.exchange,
                name=asset.name,
                as_of=latest.date,
                close=latest.close,
                deltas=deltas,
                all_time=_range_stat(bars, latest_close=latest.close),
                week_52=_range_stat(recent_bars, latest_close=latest.close),
                spark=[round(b.close, 2) for b in bars[-SPARK_SESSIONS:]],
            )
        )

    return quotes, unknown


def get_watchlist_symbols(db: Session, user_id: int) -> list[str]:
    """In the order they were added — oldest first, matching how someone
    would expect their own list to read back."""
    rows = (
        db.query(Asset.symbol)
        .join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
        .filter(WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.added_at)
        .all()
    )
    return [symbol for (symbol,) in rows]


def add_to_watchlist(db: Session, user_id: int, symbol: str) -> bool:
    """False if `symbol` isn't a known active NSE asset (the API layer
    turns that into a 404) — never silently creates a watchlist entry for
    something that doesn't exist. True whether the item was newly added or
    was already there; adding twice isn't an error, it's a no-op."""
    asset = (
        db.query(Asset)
        .filter_by(symbol=symbol.strip().upper(), market="IN", exchange="NSE", active=True)
        .one_or_none()
    )
    if asset is None:
        return False
    exists = (
        db.query(WatchlistItem).filter_by(user_id=user_id, asset_id=asset.id).one_or_none()
    )
    if exists is None:
        db.add(WatchlistItem(user_id=user_id, asset_id=asset.id))
        db.flush()
    return True


def remove_from_watchlist(db: Session, user_id: int, symbol: str) -> None:
    """Idempotent — a symbol that was never on the list, an unknown
    symbol, or an already-removed one are all not errors; the caller only
    cares that it's gone afterward, same as revoke_refresh_token for
    logout."""
    asset = (
        db.query(Asset)
        .filter_by(symbol=symbol.strip().upper(), market="IN", exchange="NSE")
        .one_or_none()
    )
    if asset is None:
        return
    db.query(WatchlistItem).filter_by(user_id=user_id, asset_id=asset.id).delete()
    db.flush()
