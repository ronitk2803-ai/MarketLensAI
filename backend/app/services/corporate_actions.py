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


def get_or_fetch_corporate_actions(db: Session, asset: Asset) -> list[CorporateActionEvent]:
    """Reads stored `corporate_action` rows; on first request for an asset
    (none stored yet), fetches once from the yfinance fallback and persists
    them, so a fresh company page still gets adjusted prices without
    depending on a separate ingestion job having already run — and every
    later request for the same asset reads from the DB instead of Yahoo."""
    rows = (
        db.query(CorporateAction)
        .filter_by(asset_id=asset.id)
        .order_by(CorporateAction.ex_date)
        .all()
    )
    if rows:
        return [
            CorporateActionEvent(
                type=row.type,
                ex_date=row.ex_date,
                ratio=float(row.ratio) if row.ratio is not None else None,
                amount=float(row.amount) if row.amount is not None else None,
            )
            for row in rows
        ]

    asset_ref = AssetRef(symbol=asset.symbol, exchange=asset.exchange, market=asset.market)
    try:
        events = YFinanceCorporateActionsProvider().get_corporate_actions(asset_ref)
    except ProviderError:
        return []

    ingest_corporate_actions(db, asset.id, events, source="yfinance_actions")
    return events
