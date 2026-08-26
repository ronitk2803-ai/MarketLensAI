"""In-app alert endpoints (Build_plan.md §S step 24). Bare JSON, not the
{data, meta} envelope — same reasoning as theses.py: that envelope's
meta.source/confidence describe market-data provenance, and an alert is
this app telling one user something about their own watchlist or thesis.

There is deliberately no delete endpoint. An alert row is also the record
that this alert has already been generated (see Alert.dedup_key), so
deleting one would let the next night's job recreate it. Marking read is
the acknowledge action; old read alerts are swept on a retention window.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models import Alert, AppUser
from app.db.session import get_db
from app.services.alerts import list_alerts, mark_all_read, unread_count

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAX_LIMIT = 200


def _to_dict(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "kind": alert.kind,
        "title": alert.title,
        "body": alert.body,
        "symbol": alert.asset.symbol,
        "exchange": alert.asset.exchange,
        # The bar date the signal was computed from — not when the row was
        # written. These are end-of-day figures surfaced hours after the
        # close, and every figure in this app carries its own timestamp.
        "as_of": alert.as_of,
        "created_at": alert.created_at,
        "read_at": alert.read_at,
    }


@router.get("")
def get_alerts(
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    alerts = list_alerts(db, current_user.id, unread_only=unread, limit=limit)
    return {
        "alerts": [_to_dict(a) for a in alerts],
        "unread_count": unread_count(db, current_user.id),
    }


@router.post("/read")
def read_all(
    current_user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Marks every unread alert read at once. A bell that only answers "is
    anything new" doesn't need per-alert acknowledgement, and per-alert
    read would mean the client tracking and PATCHing each row for no
    visible gain. Additive later if it turns out to be wanted."""
    return {"marked_read": mark_all_read(db, current_user.id)}
