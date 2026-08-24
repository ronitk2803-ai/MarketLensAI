"""Deep historical price backfill, for populating a freshly-deployed database.

Distinct from the daily job (app/jobs/daily_ingestion.py), which only closes a
~10-day gap. Seeding a year of history across the full ~2.6k-symbol NSE
universe is a different shape of problem and needs chunking:

`backfill_universe_from_bhavcopy` accumulates every bar in memory and leaves
committing to the caller, which is right for a small daily delta but means a
one-year full-universe run holds ~650k ORM objects in a single transaction —
slow, memory-hungry, and all-or-nothing, so an interruption 20 minutes in
loses everything. Running it a month at a time and committing each chunk
keeps the session small, makes progress durable and visible, and lets a
failed month be retried without redoing the rest.

Usage (inside the backend container):
    python -m app.jobs.backfill_history            # default: 365 days
    python -m app.jobs.backfill_history --days 90
    python -m app.jobs.backfill_history --days 365 --chunk-days 15
"""

import argparse
import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.services.backfill import backfill_universe_from_bhavcopy

logger = logging.getLogger(__name__)


def backfill_history(
    db: Session, *, days: int = 365, chunk_days: int = 30
) -> tuple[int, int]:
    """Backfill `days` of history in `chunk_days`-sized committed chunks.

    Returns (trading_days_found, bars_persisted) summed across chunks.
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    total_trading_days = 0
    total_bars = 0
    total_errored = 0

    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + dt.timedelta(days=chunk_days - 1), end)
        result = backfill_universe_from_bhavcopy(db, chunk_start, chunk_end)
        db.commit()
        # Drop the chunk's ORM objects; without this the session grows across
        # chunks and the per-flush cost creeps back up.
        db.expunge_all()

        total_trading_days += result.trading_days_found
        total_bars += result.bars_persisted
        total_errored += result.days_errored
        logger.info(
            "backfill_history: %s..%s -> %d trading days, %d bars, %d errored "
            "(running total %d bars, %d errored)",
            chunk_start,
            chunk_end,
            result.trading_days_found,
            result.bars_persisted,
            result.days_errored,
            total_bars,
            total_errored,
        )
        chunk_start = chunk_end + dt.timedelta(days=1)

    return total_trading_days, total_bars


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--chunk-days", type=int, default=30)
    args = parser.parse_args()

    from app.core.logging import configure_logging
    from app.db.session import SessionLocal

    configure_logging()
    # Bhavcopy fetches are one request per calendar day and log at INFO via
    # httpx; at ~365 lines that drowns out the chunk progress this job exists
    # to show.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    session = SessionLocal()
    try:
        trading_days, bars = backfill_history(
            session, days=args.days, chunk_days=args.chunk_days
        )
        logger.info(
            "backfill_history: done — %d trading days, %d bars", trading_days, bars
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
