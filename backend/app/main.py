import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimitMiddleware, sweep_all

logger = logging.getLogger(__name__)

settings = get_settings()
configure_logging()


def _run_daily_ingestion_job() -> None:
    from app.db.session import SessionLocal
    from app.jobs.daily_ingestion import run_daily_ingestion

    session = SessionLocal()
    try:
        result = run_daily_ingestion(session)
        logger.info("scheduled daily_ingestion: %s", result)
    except Exception:
        logger.exception("scheduled daily_ingestion: run failed")
    finally:
        session.close()


def _sweep_rate_limiters_job() -> None:
    try:
        dropped = sweep_all()
        if dropped:
            logger.info("rate_limit sweep: dropped %d idle buckets", dropped)
    except Exception:
        logger.exception("rate_limit sweep: run failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs regardless of settings.enable_scheduler, unlike daily_ingestion
    # below — ingestion is optional batch work, but an unbounded rate-
    # limiter dict (one entry per distinct caller ever seen) is a memory-
    # safety concern on a public deploy, not an opt-in feature. Its own
    # scheduler instance so it keeps running even when ingestion is off.
    sweep_scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Kolkata"))
    sweep_scheduler.add_job(
        _sweep_rate_limiters_job,
        trigger="interval",
        hours=1,
        id="rate_limit_sweep",
        misfire_grace_time=600,
    )
    sweep_scheduler.start()

    scheduler: BackgroundScheduler | None = None
    if settings.enable_scheduler:
        scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Kolkata"))
        scheduler.add_job(
            _run_daily_ingestion_job,
            trigger="cron",
            hour=settings.daily_ingestion_hour_ist,
            minute=0,
            id="daily_ingestion",
            misfire_grace_time=3600,
        )
        scheduler.start()
        logger.info(
            "daily_ingestion scheduled for %02d:00 Asia/Kolkata", settings.daily_ingestion_hour_ist
        )
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    sweep_scheduler.shutdown(wait=False)


app = FastAPI(title="mlai API", version="0.1.0", lifespan=lifespan)

# Added BEFORE CORSMiddleware, deliberately — Starlette wraps middleware in
# reverse of add_middleware call order, so whichever is added LAST ends up
# OUTERMOST. CORS must stay outermost so it still attaches CORS headers to
# a 429 this middleware short-circuits; added on the other side, a 429
# never reaches CORSMiddleware and arrives at a browser as an opaque,
# unreadable network error rather than a readable 429. See
# app/core/rate_limit.py for the limiter itself.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix=settings.api_v1_prefix)
