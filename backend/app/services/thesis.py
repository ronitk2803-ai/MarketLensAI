"""Thesis CRUD, ownership-scoped to the caller (Build_plan.md §X.1), plus
the daily thesis-eval job that watches each active thesis's invalidation
triggers against real data.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset, Thesis, ThesisEvent, ThesisTrigger
from app.engines.thesis import evaluate_trigger
from app.services.metric_registry import resolve_metric_value

logger = logging.getLogger(__name__)

# The eval job only touches theses in these two statuses — "invalidated"
# and "closed" are user-decided end states (Thesis.status's docstring in
# app/db/models.py); re-challenging an already-decided thesis has no point.
_EVALUABLE_STATUSES = ("active", "challenged")


@dataclass(frozen=True, slots=True)
class TriggerInput:
    metric: str
    operator: str
    threshold: float
    description: str | None = None


def find_asset_by_symbol(db: Session, symbol: str) -> Asset | None:
    """Deliberately not filtered to active=True — a thesis on a delisted
    asset is explicitly in scope (Build_plan.md §X.1's edge cases)."""
    return (
        db.query(Asset)
        .filter_by(symbol=symbol.strip().upper(), market="IN", exchange="NSE")
        .one_or_none()
    )


def create_thesis(
    db: Session,
    *,
    user_id: int,
    asset: Asset,
    title: str,
    body: str,
    stance: str,
    conviction: int,
    triggers: list[TriggerInput],
) -> Thesis:
    thesis = Thesis(
        user_id=user_id,
        asset_id=asset.id,
        title=title,
        body=body,
        stance=stance,
        conviction=conviction,
    )
    db.add(thesis)
    db.flush()
    for t in triggers:
        db.add(
            ThesisTrigger(
                thesis_id=thesis.id,
                metric=t.metric,
                operator=t.operator,
                threshold=t.threshold,
                description=t.description,
            )
        )
    db.flush()
    db.refresh(thesis)
    return thesis


def list_theses(db: Session, user_id: int) -> list[Thesis]:
    return (
        db.query(Thesis)
        .filter_by(user_id=user_id)
        .order_by(Thesis.created_at.desc())
        .all()
    )


def get_thesis(db: Session, user_id: int, thesis_id: int) -> Thesis | None:
    """None both when the thesis doesn't exist at all and when it belongs
    to a different user — the API layer turns either into an identical
    404, so a caller can never distinguish "wrong id" from "someone else's
    thesis" (same instinct as this app's login-error design not revealing
    which emails are registered)."""
    return db.query(Thesis).filter_by(id=thesis_id, user_id=user_id).one_or_none()


def update_thesis(
    db: Session,
    user_id: int,
    thesis_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    stance: str | None = None,
    conviction: int | None = None,
    status: str | None = None,
) -> Thesis | None:
    """Thesis-level fields only — triggers are immutable once created (see
    ThesisTrigger's docstring for why)."""
    thesis = get_thesis(db, user_id, thesis_id)
    if thesis is None:
        return None
    if title is not None:
        thesis.title = title
    if body is not None:
        thesis.body = body
    if stance is not None:
        thesis.stance = stance
    if conviction is not None:
        thesis.conviction = conviction
    if status is not None:
        thesis.status = status
    db.flush()
    return thesis


def delete_thesis(db: Session, user_id: int, thesis_id: int) -> bool:
    """Cascades to the thesis's triggers and events (see the ondelete=CASCADE
    FKs in app/db/models.py) — the one place this feature deletes history,
    justified because the owner is intentionally destroying their whole
    record, not editing a live one."""
    thesis = get_thesis(db, user_id, thesis_id)
    if thesis is None:
        return False
    db.delete(thesis)
    db.flush()
    return True


@dataclass(frozen=True, slots=True)
class ThesisEvalResult:
    triggers_evaluated: int = 0
    events_created: int = 0
    errors: int = 0


def run_thesis_eval(db: Session) -> ThesisEvalResult:
    """For every active/challenged thesis's triggers: resolve the metric,
    check it against the trigger, and write a ThesisEvent (once, flipping
    the thesis to "challenged") only on a false -> true breach transition
    — never repeatedly for a trigger that's already been breached since
    the last run. An unevaluable trigger (resolve_metric_value returns
    None) is left exactly as it was — no event, no state change; Build_plan
    §X.1 is explicit that missing data must never read as "not breached."

    Queries assets straight off thesis_trigger rather than reusing
    app/jobs/daily_ingestion.py's active-equity-universe helper — that
    filters to active NSE equities, which would silently skip the
    delisted-asset case this feature explicitly keeps in scope.
    """
    rows = (
        db.query(ThesisTrigger, Thesis, Asset)
        .join(Thesis, Thesis.id == ThesisTrigger.thesis_id)
        .join(Asset, Asset.id == Thesis.asset_id)
        .filter(Thesis.status.in_(_EVALUABLE_STATUSES))
        .all()
    )

    evaluated = 0
    events_created = 0
    errors = 0
    for trigger, thesis, asset in rows:
        evaluated += 1
        try:
            observed = resolve_metric_value(db, asset, trigger.metric)
            breached = evaluate_trigger(
                trigger.operator, float(trigger.threshold), observed
            )
        except Exception:
            errors += 1
            logger.exception(
                "thesis_eval: failed for thesis %s trigger %s", thesis.id, trigger.id
            )
            continue

        if breached is None:
            continue  # cannot evaluate this cycle — state untouched

        if breached and not trigger.currently_breached:
            db.add(
                ThesisEvent(
                    thesis_id=thesis.id,
                    trigger_id=trigger.id,
                    observed_value=observed,
                )
            )
            trigger.currently_breached = True
            events_created += 1
            if thesis.status == "active":
                thesis.status = "challenged"
        elif not breached and trigger.currently_breached:
            # Un-breaches silently — Build_plan §X.1 says an event is
            # written "on fire," not on recovery, and thesis.status stays
            # "challenged" (a historical fact, not live state) even once
            # every trigger has un-breached.
            trigger.currently_breached = False

    db.flush()
    return ThesisEvalResult(
        triggers_evaluated=evaluated, events_created=events_created, errors=errors
    )
