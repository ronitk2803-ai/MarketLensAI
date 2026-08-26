"""The daily unattended ingestion job (Build_plan.md §S step 15 / §Q MVP
scope): prices -> corporate actions -> scores -> thesis-trigger eval, over
the active equity universe. Not tied to any scheduler — callable directly
(`python -m app.jobs.daily_ingestion`) so it works equally as an
APScheduler job (wired into app.main's lifespan for the in-process MVP
default), a platform cron trigger (Render/Fly Cron Jobs), or a GitHub
Actions schedule — whichever fits how this actually gets deployed.

Deliberately excludes:
- Universe refresh (re-seeding from Upstox's instrument dump): monthly per
  Build_plan.md §2, not daily — run app.services.universe on its own
  cadence, not from here.
- News refresh for the whole universe: the per-company lazy-fetch + 1-hour
  cooldown (app/services/news.py) already keeps anything actually being
  viewed fresh; blindly fetching news for the whole universe daily would be
  hundreds of Google News calls for stocks nobody is looking at, which
  contradicts product_principles.md's "minimize API calls."

One asset's failure (a Yahoo hiccup, a delisted ticker) is logged and
skipped rather than aborting the whole batch — 259 other assets shouldn't
go stale because of one.
"""

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.db.models import Asset, Company, ScoreProfile
from app.services.alerts import AlertGenerationResult, generate_alerts
from app.services.backfill import BackfillResult, backfill_universe_from_bhavcopy
from app.services.corporate_actions import get_or_fetch_corporate_actions
from app.services.scoring import get_or_compute_score
from app.services.thesis import run_thesis_eval

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DailyIngestionResult:
    backfill: BackfillResult
    corporate_actions_processed: int
    corporate_actions_errors: int
    scores_computed: int
    scores_errors: int
    thesis_events_created: int
    thesis_eval_errors: int
    alerts_created: int = 0
    alerts_pruned: int = 0


def _active_equity_universe(db: Session) -> list[Asset]:
    # Company/Industry are eager-loaded because scoring resolves a profile
    # per asset through asset.company.industry (app/services/scoring.py's
    # resolve_profile_for_asset). Both relationships are lazy-select by
    # default, so without this a 500-asset run fires ~1000 extra queries.
    return (
        db.query(Asset)
        .options(joinedload(Asset.company).joinedload(Company.industry))
        .filter_by(market="IN", exchange="NSE", active=True, asset_class="EQUITY")
        .all()
    )


def run_daily_ingestion(
    db: Session, *, price_lookback_days: int = 10, with_alerts: bool = True
) -> DailyIngestionResult:
    """`with_alerts=False` is for tests: this job commits for real, and
    generating alerts off the synthetic bars the test fixtures stub in
    would inject fabricated signals into whatever accounts exist on the
    dev database."""
    end = dt.date.today()
    start = end - dt.timedelta(days=price_lookback_days)
    backfill = backfill_universe_from_bhavcopy(db, start, end)
    db.commit()
    logger.info("daily_ingestion: price backfill %s", backfill)

    assets = _active_equity_universe(db)

    ca_processed = 0
    ca_errors = 0
    for asset in assets:
        try:
            get_or_fetch_corporate_actions(db, asset)
            ca_processed += 1
        except Exception:
            ca_errors += 1
            logger.exception("daily_ingestion: corporate actions failed for %s", asset.symbol)
    db.commit()

    scores_computed = 0
    scores_errors = 0
    # Resolved once per distinct profile rather than once per asset — there
    # are a couple of profiles across hundreds of assets.
    profile_cache: dict[str, ScoreProfile] = {}
    for asset in assets:
        try:
            get_or_compute_score(db, asset, profile_cache=profile_cache)
            scores_computed += 1
        except Exception:
            scores_errors += 1
            logger.exception("daily_ingestion: scoring failed for %s", asset.symbol)
    db.commit()

    # Runs last and deliberately not per-asset from `assets` above — a
    # thesis can reference a delisted/inactive asset (Build_plan.md
    # §X.1's edge cases), which `_active_equity_universe` filters out, so
    # this queries straight off thesis_trigger instead (see
    # run_thesis_eval's docstring).
    thesis_eval = run_thesis_eval(db)
    db.commit()
    logger.info("daily_ingestion: thesis eval %s", thesis_eval)

    # Last, and after thesis eval commits — it reads the ThesisEvent rows
    # that step just wrote. Idempotent, so a re-run (weekend, missed-run
    # catch-up) produces nothing new.
    alerts = AlertGenerationResult()
    if with_alerts:
        alerts = generate_alerts(db)
        db.commit()
        logger.info("daily_ingestion: alerts %s", alerts)

    result = DailyIngestionResult(
        backfill=backfill,
        corporate_actions_processed=ca_processed,
        corporate_actions_errors=ca_errors,
        scores_computed=scores_computed,
        scores_errors=scores_errors,
        thesis_events_created=thesis_eval.events_created,
        thesis_eval_errors=thesis_eval.errors,
        alerts_created=alerts.thesis_alerts + alerts.watchlist_alerts,
        alerts_pruned=alerts.pruned,
    )
    logger.info("daily_ingestion: done %s", result)
    return result


if __name__ == "__main__":
    from app.core.logging import configure_logging

    configure_logging()
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        outcome = run_daily_ingestion(session)
        print(outcome)
    finally:
        session.close()
