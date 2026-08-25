"""Persists `CorporateActionEvent`s from a provider into `corporate_action`."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Asset, CorporateAction
from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError
from app.providers.india.yfinance_actions import YFinanceCorporateActionsProvider


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
    created = 0
    updated = 0
    for event in events:
        row = (
            db.query(CorporateAction)
            .filter_by(asset_id=asset_id, type=event.type, ex_date=event.ex_date)
            .one_or_none()
        )
        if row is None:
            db.add(
                CorporateAction(
                    asset_id=asset_id,
                    type=event.type,
                    ex_date=event.ex_date,
                    ratio=_decimal(event.ratio),
                    amount=_decimal(event.amount),
                    source=source,
                )
            )
            created += 1
        else:
            row.ratio = _decimal(event.ratio)
            row.amount = _decimal(event.amount)
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
    db: Session, asset_ids: list[int]
) -> dict[int, list[CorporateActionEvent]]:
    """Same pure-DB-read contract as get_stored_corporate_actions, for the
    whole universe in one query instead of one per asset.

    The screener adjusts every asset it loads, so the per-asset version
    meant ~500 round trips per screen run — and the homepage fires four
    screens at once. Assets with no stored actions are simply absent from
    the result; the caller treats a missing key as "no adjustments", which
    is what adjust_bars does with an empty list anyway."""
    if not asset_ids:
        return {}
    rows = (
        db.query(CorporateAction)
        .filter(CorporateAction.asset_id.in_(asset_ids))
        .order_by(CorporateAction.asset_id, CorporateAction.ex_date)
        .all()
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
    (none stored yet), fetches once from the yfinance fallback and persists
    them, so a fresh company page still gets adjusted prices without
    depending on a separate ingestion job having already run — and every
    later request for the same asset reads from the DB instead of Yahoo."""
    rows = get_stored_corporate_actions(db, asset.id)
    if rows:
        return rows

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        events = YFinanceCorporateActionsProvider().get_corporate_actions(asset_ref)
    except ProviderError:
        return []

    ingest_corporate_actions(db, asset.id, events, source="yfinance_actions")
    return events
