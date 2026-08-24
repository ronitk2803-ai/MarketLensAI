"""Batch price backfill from NSE Bhavcopy — one HTTP request per trading
day covers the *whole* exchange (NSEBhavcopyProvider.get_day_bars), unlike
the per-symbol path in prices.py. This is the intended path for populating
history across a universe (Build_plan.md §G/§K); a live page request must
never do this per-asset (see prices.py's MAX_ON_DEMAND_FETCH_DAYS).

A trimmed-down version of what the real "daily ingestion job" (Build_plan.md
§S step 15, not yet built) would run automatically — this module is written
so that job can reuse it directly rather than duplicating the logic.
"""

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.models import Bar
from app.providers.errors import ProviderError
from app.providers.india.nse_bhavcopy import BhavcopyRow, NSEBhavcopyProvider
from app.services.prices import persist_bars

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    trading_days_found: int
    days_checked: int
    bars_persisted: int
    days_errored: int = 0


def _bhavcopy_row_to_bar(row: BhavcopyRow) -> Bar:
    return Bar(
        date=row.date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        delivery_qty=row.delivery_qty,
        delivery_pct=row.delivery_pct,
    )


def backfill_universe_from_bhavcopy(
    db: Session, start: dt.date, end: dt.date, *, provider: NSEBhavcopyProvider | None = None
) -> BackfillResult:
    provider = provider or NSEBhavcopyProvider()

    symbol_to_asset_id = {
        row.symbol: row.id
        for row in db.query(Asset).filter_by(market="IN", exchange="NSE", active=True)
    }

    # Accumulate per-asset across the whole range so each asset is persisted
    # (and flushed) once, not once per bar — a 90-day x 300-asset backfill
    # is ~300 flushes this way instead of ~27,000.
    bars_by_asset: dict[int, list[Bar]] = {}
    trading_days_found = 0
    days_checked = 0
    days_errored = 0
    current = start
    while current <= end:
        days_checked += 1
        try:
            day_rows = provider.get_day_bars(current)
        except ProviderError:
            # One bad day (verified live: NSE's own archive occasionally
            # mislabels a file — see nse_bhavcopy.parse_bhavcopy) must not
            # cost every other day in this chunk. Before this, a single
            # unhandled day meant `bars_by_asset` never reached the persist
            # loop below, so a 5-year backfill silently lost 3 years of
            # otherwise-good data to one anomalous date in the middle.
            days_errored += 1
            logger.warning("backfill: skipping %s after a provider error", current, exc_info=True)
            current += dt.timedelta(days=1)
            continue
        if day_rows:
            trading_days_found += 1
        for row in day_rows:
            asset_id = symbol_to_asset_id.get(row.symbol)
            if asset_id is None:
                continue
            bars_by_asset.setdefault(asset_id, []).append(_bhavcopy_row_to_bar(row))
        current += dt.timedelta(days=1)

    bars_persisted = 0
    for asset_id, bars in bars_by_asset.items():
        persist_bars(db, asset_id, bars, "nse_bhavcopy")
        bars_persisted += len(bars)

    return BackfillResult(
        trading_days_found=trading_days_found,
        days_checked=days_checked,
        bars_persisted=bars_persisted,
        days_errored=days_errored,
    )
