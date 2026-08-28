"""One-time deep corporate-actions backfill from NSE (Build_plan.md §U.11 /
SUMMARISER.md §9.1 — the highest-impact live data bug at the time this was
written).

Distinct from the daily job's rolling ~13-month refresh
(`app.jobs.daily_ingestion`'s `CORPORATE_ACTIONS_LOOKBACK_DAYS` window):
that keeps recent history current on every run, but a database seeded
before this provider existed (or before a given asset was ingested) can
still be missing years-old bonuses and demergers — the exact §U.11 gap
(BAJFINANCE's 2025-06-16 bonus, ABFRL's and VEDL's demergers, and others).
This walks the full history NSE's endpoint covers and upserts everything in
one pass, per `refresh_corporate_actions_from_nse`'s idempotent-upsert
contract — safe to re-run.

Unlike `backfill_history.py`, this needs no per-day chunking: the NSE
endpoint takes one date range and returns every listed equity's actions in
it in a single response (~12,300 rows for a 5-year span, observed live
2026-08-29) — it is shaped like `nse_bhavcopy.py`'s bulk file, not like
Upstox's one-instrument-per-request history. `--chunk-years` still exists
so a very long backfill commits progress durably instead of holding one
giant transaction, mirroring `backfill_history.py`'s reasoning.

Usage (inside the backend container):
    python -m app.jobs.backfill_corporate_actions                  # since 2020-01-01
    python -m app.jobs.backfill_corporate_actions --from-year 2019
"""

import argparse
import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.services.corporate_actions import refresh_corporate_actions_from_nse

logger = logging.getLogger(__name__)


def _active_equity_universe(db: Session) -> list[Asset]:
    # Same filter as daily_ingestion.py's — this backfill only matters for
    # the assets the rest of the pipeline actually scores/screens.
    return (
        db.query(Asset)
        .filter_by(market="IN", exchange="NSE", active=True, asset_class="EQUITY")
        .all()
    )


def backfill_corporate_actions(
    db: Session, *, from_year: int = 2020, chunk_years: int = 2
) -> int:
    """Backfill NSE corporate actions from `from_year`-01-01 through today,
    in `chunk_years`-sized committed chunks. Returns total rows ingested
    (created + updated, per `IngestResult.total`)."""
    assets = _active_equity_universe(db)
    end = dt.date.today()
    total = 0

    chunk_start = dt.date(from_year, 1, 1)
    while chunk_start <= end:
        chunk_end = min(
            dt.date(chunk_start.year + chunk_years, 1, 1) - dt.timedelta(days=1), end
        )
        result = refresh_corporate_actions_from_nse(
            db, assets, from_date=chunk_start, to_date=chunk_end
        )
        db.commit()
        total += result.total
        logger.info(
            "backfill_corporate_actions: %s -> %s: %s", chunk_start, chunk_end, result
        )
        chunk_start = chunk_end + dt.timedelta(days=1)

    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2020)
    parser.add_argument("--chunk-years", type=int, default=2)
    args = parser.parse_args()

    from app.core.logging import configure_logging
    from app.db.session import SessionLocal

    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    session = SessionLocal()
    try:
        total = backfill_corporate_actions(
            session, from_year=args.from_year, chunk_years=args.chunk_years
        )
        logger.info("backfill_corporate_actions: done — %d rows ingested", total)
    finally:
        session.close()


if __name__ == "__main__":
    main()
