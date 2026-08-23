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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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


app = FastAPI(title="mlai API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix=settings.api_v1_prefix)
