from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_size=10, max_overflow=20 (30 connections max), up from SQLAlchemy's
# defaults of 5+10=15. Render runs this container as a single uvicorn
# worker with no --workers flag, so there is exactly one engine and one
# pool for the whole process — every concurrent request (sync route
# handlers run in Starlette's threadpool) checks a connection out of the
# SAME pool for its whole request, via get_db()'s one-Session-per-request
# pattern.
#
# The default 15 was hit live: a burst of `/opportunities` requests a few
# minutes after a deploy produced 16 `QueuePool limit of size 5 overflow
# 10 reached, connection timed out` 500s in 14 seconds (2026-09-01,
# SUMMARISER.md §8.6). The homepage alone opens 4 of these concurrently
# (frontend/app/page.tsx's Promise.all over BOARDS), before counting any
# other visitor or endpoint. DATABASE_URL is Neon's pooled endpoint
# (Deployment.md §1), which fronts far more capacity than a single Render
# free-tier instance will ever open — so headroom here costs nothing on
# the database side, only the (negligible, for a service this size) memory
# of idle pooled connections.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    """Commits on a clean request, rolls back on any exception.

    Missing this commit is a real bug that was live for the whole of step 8
    until caught by end-to-end testing: every write a service made (price
    persistence, corporate-action ingestion, fetch-log records) looked fine
    within the request — a session sees its own uncommitted writes — then
    silently vanished on `close()`, so nothing ever actually accumulated
    across requests.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
