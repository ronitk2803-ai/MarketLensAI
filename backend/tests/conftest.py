import pytest
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()
