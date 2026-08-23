"""Persists `CorporateActionEvent`s from a provider into `corporate_action`."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CorporateAction
from app.domain.models import CorporateActionEvent


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
