"""Portfolio holdings CRUD, ownership-scoped to the caller, plus
multi-broker (Zerodha, Upstox) holdings-file import (Build_plan.md P1
build-sequence step 17).

A user can hold the same asset across multiple demat accounts plus a
hand-entered position — each is stored as its own `Holding` row ("lot"),
tagged with `broker`. Every read consolidates all of a user's lots for
an asset into one `HoldingValuation` (summed quantity, weighted-average
cost basis), with the underlying `lots` still exposed so the UI can show
and edit each broker's position individually.

P&L is computed live on every read from whatever daily_ingestion has
already landed in PriceOHLCV — same "stored-data-only, recompute on every
request rather than cache a number that can go stale" discipline
watchlist.py's get_watchlist_quotes already applies. No live external
price call is made here.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import Asset, Holding, PriceOHLCV
from app.engines.adjustment import adjust_bars
from app.engines.csv_import import ParsedHoldingRow, parse_holdings_file
from app.services.corporate_actions import get_stored_corporate_actions
from app.services.prices import row_to_bar
from app.services.thesis import find_asset_by_symbol

Broker = Literal["zerodha", "upstox"]

__all__ = [
    "BrokerLot",
    "HoldingValuation",
    "ImportRowResult",
    "ImportSummary",
    "add_or_update_holding",
    "delete_holding",
    "get_holding",
    "get_valuation_for_asset",
    "import_holdings_file",
    "list_holdings",
    "update_holding",
]


@dataclass(frozen=True, slots=True)
class BrokerLot:
    holding_id: int
    broker: str
    quantity: float
    avg_cost: float


@dataclass(frozen=True, slots=True)
class HoldingValuation:
    symbol: str
    exchange: str
    name: str
    quantity: float
    avg_cost: float
    last_price: float | None
    as_of: dt.date | None
    market_value: float | None
    cost_basis: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    lots: list[BrokerLot]


def _load_latest_close(db: Session, asset: Asset) -> tuple[float | None, dt.date | None]:
    """Identical pattern to watchlist._load_all_adjusted_bars — reads
    whatever daily_ingestion already landed, adjusts for corporate
    actions, takes the last bar. No live external call (Build_plan §K)."""
    rows = db.query(PriceOHLCV).filter_by(asset_id=asset.id).order_by(PriceOHLCV.date).all()
    if not rows:
        return None, None
    bars = adjust_bars([row_to_bar(r) for r in rows], get_stored_corporate_actions(db, asset.id))
    if not bars:
        return None, None
    return bars[-1].close, bars[-1].date


def _consolidate(db: Session, asset: Asset, holdings: list[Holding]) -> HoldingValuation:
    """Sums every lot for one asset into a single valuation. `quantity`
    for every lot is guaranteed > 0 (enforced at the Pydantic layer for
    manual add/edit, and in the CSV/XLSX parser for imports), so
    total_quantity here can never be zero — the weighted-average division
    is always safe."""
    last_price, as_of = _load_latest_close(db, asset)
    lots = [
        BrokerLot(
            holding_id=h.id, broker=h.broker, quantity=float(h.quantity), avg_cost=float(h.avg_cost)
        )
        for h in holdings
    ]
    quantity = sum(lot.quantity for lot in lots)
    cost_basis = sum(lot.quantity * lot.avg_cost for lot in lots)
    avg_cost = cost_basis / quantity
    market_value = quantity * last_price if last_price is not None else None
    unrealized_pnl = market_value - cost_basis if market_value is not None else None
    unrealized_pnl_pct = (
        unrealized_pnl / cost_basis * 100
        if unrealized_pnl is not None and cost_basis
        else None
    )
    return HoldingValuation(
        symbol=asset.symbol,
        exchange=asset.exchange,
        name=asset.name,
        quantity=quantity,
        avg_cost=avg_cost,
        last_price=last_price,
        as_of=as_of,
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        lots=lots,
    )


def list_holdings(db: Session, user_id: int) -> list[HoldingValuation]:
    holdings = (
        db.query(Holding).filter_by(user_id=user_id).order_by(Holding.created_at).all()
    )
    by_asset: dict[int, list[Holding]] = {}
    for h in holdings:
        by_asset.setdefault(h.asset_id, []).append(h)
    return [_consolidate(db, group[0].asset, group) for group in by_asset.values()]


def get_valuation_for_asset(db: Session, user_id: int, asset_id: int) -> HoldingValuation:
    """Same consolidation as list_holdings, scoped to one asset — used by
    the add/edit endpoints so their response is shaped identically to
    what GET /portfolio would show for that asset, never a lone-lot view
    that could disagree with it."""
    holdings = db.query(Holding).filter_by(user_id=user_id, asset_id=asset_id).all()
    return _consolidate(db, holdings[0].asset, holdings)


def get_holding(db: Session, user_id: int, holding_id: int) -> Holding | None:
    """None both when the holding doesn't exist and when it belongs to a
    different user — the API layer turns either into an identical 404,
    same discipline as thesis.get_thesis."""
    return db.query(Holding).filter_by(id=holding_id, user_id=user_id).one_or_none()


def add_or_update_holding(
    db: Session, user_id: int, symbol: str, *, quantity: float, avg_cost: float
) -> Holding | None:
    """None if `symbol` doesn't resolve (API -> 404), mirroring
    add_to_watchlist's contract. Unlike watchlist's add, re-submitting an
    already-held symbol updates quantity/avg_cost in place rather than
    being a no-op — that's the whole point of "I bought 10 more."

    Scoped to broker="manual" specifically — a user can also hold this
    asset via one or more broker imports, which are separate lots
    (separate rows) this function must never touch."""
    asset = find_asset_by_symbol(db, symbol)
    if asset is None:
        return None
    holding = (
        db.query(Holding)
        .filter_by(user_id=user_id, asset_id=asset.id, broker="manual")
        .one_or_none()
    )
    if holding is None:
        holding = Holding(
            user_id=user_id,
            asset_id=asset.id,
            broker="manual",
            quantity=Decimal(str(quantity)),
            avg_cost=Decimal(str(avg_cost)),
        )
        db.add(holding)
    else:
        holding.quantity = Decimal(str(quantity))
        holding.avg_cost = Decimal(str(avg_cost))
    db.flush()
    db.refresh(holding)
    return holding


def update_holding(
    db: Session,
    user_id: int,
    holding_id: int,
    *,
    quantity: float | None = None,
    avg_cost: float | None = None,
) -> Holding | None:
    holding = get_holding(db, user_id, holding_id)
    if holding is None:
        return None
    if quantity is not None:
        holding.quantity = Decimal(str(quantity))
    if avg_cost is not None:
        holding.avg_cost = Decimal(str(avg_cost))
    db.flush()
    return holding


def delete_holding(db: Session, user_id: int, holding_id: int) -> bool:
    holding = get_holding(db, user_id, holding_id)
    if holding is None:
        return False
    db.delete(holding)
    db.flush()
    return True


@dataclass(frozen=True, slots=True)
class ImportRowResult:
    row_number: int
    symbol: str
    status: str  # "imported" | "skipped"
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ImportSummary:
    imported: int = 0
    skipped: int = 0
    rows: list[ImportRowResult] = field(default_factory=list)


def import_holdings_file(
    db: Session, user_id: int, raw_bytes: bytes, filename: str, *, broker: Broker
) -> ImportSummary:
    """Parses + resolves symbols + replaces this user's previously
    imported lots for this one broker, all in the caller's transaction
    (no commit here — app/db/session.py's get_db commits once at the end
    of the request, or rolls back the whole thing on any exception, so
    the delete+insert is atomic without this function doing anything
    special).

    A holdings file is a snapshot ("this is what I hold right now at
    this broker"), not a delta — a successful import deletes every
    existing Holding row for this (user, broker) first (a symbol that
    dropped out of a re-imported file means that position was closed at
    this broker), then re-inserts from the new file. Lots from any OTHER
    broker, and manual lots, are never touched — they live under a
    different `broker` value, so they're outside this delete's scope
    entirely; there's no more "takeover" case to handle (the old
    single-row-per-asset schema needed one, per-broker uniqueness
    doesn't).

    Only replaces if at least one row resolved: an all-garbage file
    (wrong file, every symbol unrecognized) must not wipe this broker's
    existing holdings down to zero — it returns a summary with 0 imported
    and each row's specific skip reason instead, leaving existing lots
    untouched.

    Raises ValueError (from parse_holdings_file) for structural failures
    — the API layer maps that to a 400.
    """
    parsed = parse_holdings_file(raw_bytes, filename)

    resolved: list[tuple[Asset, ParsedHoldingRow]] = []
    results: list[ImportRowResult] = []
    seen_asset_ids: set[int] = set()
    for row in parsed.rows:
        asset = find_asset_by_symbol(db, row.symbol)
        if asset is None:
            results.append(
                ImportRowResult(
                    row.row_number, row.symbol, "skipped", f"unknown symbol: {row.symbol}"
                )
            )
            continue
        if asset.id in seen_asset_ids:
            # Two distinct symbol strings resolving to the same asset
            # (rare, but the unique constraint would otherwise 500 on
            # flush) — keep the first, skip the rest.
            results.append(
                ImportRowResult(
                    row.row_number, row.symbol, "skipped", "duplicate holding for this asset"
                )
            )
            continue
        seen_asset_ids.add(asset.id)
        resolved.append((asset, row))

    for err in parsed.errors:
        results.append(ImportRowResult(err.row_number, "", "skipped", err.reason))

    if resolved:
        db.query(Holding).filter_by(user_id=user_id, broker=broker).delete()
        db.flush()
        for asset, row in resolved:
            db.add(
                Holding(
                    user_id=user_id,
                    asset_id=asset.id,
                    broker=broker,
                    quantity=Decimal(str(row.quantity)),
                    avg_cost=Decimal(str(row.avg_cost)),
                )
            )
            results.append(ImportRowResult(row.row_number, row.symbol, "imported"))
        db.flush()

    results.sort(key=lambda r: r.row_number)
    imported = sum(1 for r in results if r.status == "imported")
    return ImportSummary(imported=imported, skipped=len(results) - imported, rows=results)
