"""Adjusted price bars for a company — shared by the /prices and
/technicals endpoints so both read from one cache/adjustment path instead
of duplicating it (and so /prices doesn't pay for indicator computation it
doesn't need)."""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import Bar
from app.engines.adjustment import adjust_bars
from app.services.corporate_actions import get_or_fetch_corporate_actions
from app.services.prices import get_price_history


def get_adjusted_bars(
    db: Session, asset: Asset, *, lookback_days: int
) -> tuple[list[Bar], str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=lookback_days)

    raw_bars, price_source = get_price_history(db, asset, start, end)
    actions = get_or_fetch_corporate_actions(db, asset)
    bars = adjust_bars(raw_bars, actions)
    return bars, price_source
