from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
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
