"""Persists `CorporateActionEvent`s from a provider into `corporate_action`."""

import datetime as dt
import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Asset, CorporateAction
from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.nse_actions import NSECorporateActionsProvider, fetch_actions_bulk
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider

logger = logging.getLogger(__name__)


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class IngestResult:
    created: int
    updated: int
    total: int


def ingest_corporate_actions(
    db: Session, asset_id: int, events: list[CorporateActionEvent], *, source: str
) -> IngestResult:
    """Upserts each event into `corporate_action`, keyed on
    `(asset_id, type, ex_date)` — plus `amount` for dividends.

    Dividends are the exception because a company routinely pays more than
    one on a single ex-date (interim + final + special), all typed
    `"dividend"`, so the amount is part of their identity — NESTLEIND's
    2026-07-10 ₹5 + ₹2 is a real pair, not a duplicate. Splits, bonuses,
    rights and demergers are unique per `(type, ex_date)`, and a changed
    ratio there is a correction to apply in place (360ONE's 2x recorded
    against a real 4x move, SUMMARISER.md §9.1).

    The `seen` guard and `.first()` (not `.one_or_none()`) both exist
    because the session is `autoflush=False`: two matching events in one
    `events` list — NSE lists some actions twice, e.g. a SIYSIL demerger
    live 2026-08 — would otherwise each miss the other's un-flushed INSERT
    and create a duplicate row, which then makes the next run's lookup
    ambiguous and raises `MultipleResultsFound`. This shipped that way; the
    guard now also tolerates rows an earlier run already duplicated.
    """
    created = 0
    updated = 0
    seen: set[tuple[str, dt.date, Decimal | None]] = set()
    for event in events:
        ratio = _decimal(event.ratio)
        amount = _decimal(event.amount)
        key_amount = amount if event.type == "dividend" else None
        key = (event.type, event.ex_date, key_amount)
        if key in seen:
            continue
        seen.add(key)

        query = db.query(CorporateAction).filter_by(
            asset_id=asset_id, type=event.type, ex_date=event.ex_date
        )
        if event.type == "dividend":
            query = query.filter(
                CorporateAction.amount.is_(None)
                if amount is None
                else CorporateAction.amount == amount
            )
        row = query.order_by(CorporateAction.id).first()

        if row is None:
            db.add(
                CorporateAction(
                    asset_id=asset_id,
                    type=event.type,
                    ex_date=event.ex_date,
                    ratio=ratio,
                    amount=amount,
                    source=source,
                )
            )
            created += 1
        else:
            row.ratio = ratio
            row.amount = amount
            row.source = source
            updated += 1
    db.flush()
    return IngestResult(created=created, updated=updated, total=len(events))


def get_stored_corporate_actions(db: Session, asset_id: int) -> list[CorporateActionEvent]:
    """Pure DB read, no fetch — for callers (like the opportunity screener)
    that must never trigger a live provider call per asset (Build_plan.md
    §K: screens "run entirely against stored data, no live API storms")."""
    rows = (
        db.query(CorporateAction).filter_by(asset_id=asset_id).order_by(CorporateAction.ex_date).all()
    )
    return [
        CorporateActionEvent(
            type=row.type,
            ex_date=row.ex_date,
            ratio=float(row.ratio) if row.ratio is not None else None,
            amount=float(row.amount) if row.amount is not None else None,
        )
        for row in rows
    ]


def get_stored_corporate_actions_bulk(
    db: Session, asset_ids: list[int], *, since: dt.date | None = None
) -> dict[int, list[CorporateActionEvent]]:
    """Same pure-DB-read contract as get_stored_corporate_actions, for the
    whole universe in one query instead of one per asset.

    The screener adjusts every asset it loads, so the per-asset version
    meant ~500 round trips per screen run — and the homepage fires four
    screens at once. Assets with no stored actions are simply absent from
    the result; the caller treats a missing key as "no adjustments", which
    is what adjust_bars does with an empty list anyway.

    `since` drops actions that provably cannot affect the caller's bars.
    engines/adjustment.py's `_cumulative` only multiplies in a factor whose
    `ex_date` is *strictly after* the bar being adjusted, so for a universe
    loaded with `date >= cutoff`, every action on or before that cutoff is
    a guaranteed no-op. Passing it is therefore output-identical, not an
    approximation — and it is the difference between shipping the whole
    `corporate_action` table (15,591 rows on the hosted universe, most of
    them years old) over the wire on every single screen run and shipping
    the handful inside the window. Left None by default so callers that
    genuinely want full history (the per-asset company page) are unchanged.

    Columns, not entities, for the same reason as the universe bar loader
    (services/opportunities.py, SUMMARISER.md §8.6): this builds plain
    `CorporateActionEvent`s and never touches the other columns, so
    hydrating a full ORM instance per row bought nothing and cost a
    Session identity-map entry that kept every row alive."""
    if not asset_ids:
        return {}
    filters: list[ColumnElement[bool]] = [CorporateAction.asset_id.in_(asset_ids)]
    if since is not None:
        filters.append(CorporateAction.ex_date > since)
    rows = db.execute(
        select(
            CorporateAction.asset_id,
            CorporateAction.type,
            CorporateAction.ex_date,
            CorporateAction.ratio,
            CorporateAction.amount,
        )
        .where(*filters)
        .order_by(CorporateAction.asset_id, CorporateAction.ex_date)
    )
    by_asset: dict[int, list[CorporateActionEvent]] = {}
    for row in rows:
        by_asset.setdefault(row.asset_id, []).append(
            CorporateActionEvent(
                type=row.type,
                ex_date=row.ex_date,
                ratio=float(row.ratio) if row.ratio is not None else None,
                amount=float(row.amount) if row.amount is not None else None,
            )
        )
    return by_asset


def get_or_fetch_corporate_actions(db: Session, asset: Asset) -> list[CorporateActionEvent]:
    """Reads stored `corporate_action` rows; on first request for an asset
    (none stored yet), fetches once and persists, so a fresh company page
    still gets adjusted prices without depending on a separate ingestion
    job having already run — and every later request for the same asset
    reads from the DB instead of a live call.

    NSE first, yfinance as fallback (Build_plan.md §F's ordered-fallback
    registry pattern, and API_Sources.md §6's stated primary/fallback
    order) — see app/providers/india/nse_actions.py's module docstring for
    why NSE is reachable again after being believed blocked. Any single
    provider failing here just falls through to the next; both failing
    returns empty exactly as the yfinance-only version did."""
    rows = get_stored_corporate_actions(db, asset.id)
    if rows:
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    for provider, source in (
        (NSECorporateActionsProvider(), "nse_actions"),
        (YFinanceCorporateActionsProvider(), "yfinance_actions"),
    ):
        try:
            events = provider.get_corporate_actions(asset_ref)
        except ProviderError:
            continue
        ingest_corporate_actions(db, asset.id, events, source=source)
        return events
    return []


def refresh_corporate_actions_from_nse(
    db: Session, assets: list[Asset], *, from_date: dt.date, to_date: dt.date
) -> IngestResult:
    """One NSE bulk call covering every listed equity's actions in
    `[from_date, to_date]`, upserted per matching asset — the batch
    counterpart to `get_or_fetch_corporate_actions`'s single-asset lazy
    path. Unlike that lazy path (which only ever fetches once per asset,
    the moment it has zero stored rows), this is meant to run on *every*
    ingestion regardless of what's already stored — it is one HTTP call
    for the whole market, so re-running it daily costs nothing, and it is
    the only thing that catches a *new* action for an asset that already
    had older rows (the lazy path's "already have rows" short-circuit
    would otherwise never see it).

    On a total NSE failure, returns an empty result rather than falling
    back to a 500-call yfinance sweep here — daily_ingestion.py's existing
    per-asset `get_or_fetch_corporate_actions` loop already runs after
    this and is the yfinance safety net for any asset still left with zero
    stored rows, so the fallback chain is preserved without duplicating it.
    """
    by_symbol_asset = {asset.symbol: asset for asset in assets}
    try:
        by_symbol_events = fetch_actions_bulk(from_date, to_date)
    except ProviderError:
        logger.exception("refresh_corporate_actions_from_nse: bulk fetch failed")
        return IngestResult(created=0, updated=0, total=0)

    created = updated = total = 0
    for symbol, events in by_symbol_events.items():
        asset = by_symbol_asset.get(symbol)
        if asset is None:
            continue  # not in our active universe (delisted, ETF, different series)
        result = ingest_corporate_actions(db, asset.id, events, source="nse_actions")
        created += result.created
        updated += result.updated
        total += result.total
    return IngestResult(created=created, updated=updated, total=total)
