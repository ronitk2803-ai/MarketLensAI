import pytest
from sqlalchemy.orm import Session

from app.core.rate_limit import reset_all as reset_rate_limiters
from app.db.session import SessionLocal
from app.services.opportunities import clear_screen_cache


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_module_caches() -> None:
    """The rate limiter's state is a module-level global (app/core/
    rate_limit.py), so every request across the whole test process shares
    it — same as a real running server. Without resetting between tests,
    the many existing suites that legitimately call rate-limited routes
    (register, login, /screener/run, /opportunities, /quotes, /ai-summary)
    dozens of times each across different files would start failing
    partway through a full run, not because anything they test is wrong
    but because an earlier, unrelated test already spent that key's
    budget. Autouse so every test gets this for free, matching the
    isolation the `db` fixture's rollback already gives the database —
    tests that specifically want to exercise a limit still can, starting
    from a clean bucket each time.

    The opportunity-screen cache (app/services/opportunities.py) is the
    same shape of global and needs the same treatment, for a sharper
    reason: it is keyed only on (screen_id, sessions), so without this a
    test that seeds a universe and asserts on the hits it produces would
    be served the *previous* test's result for the same screen — a
    false pass that gets worse the more screen tests exist. Cleared
    before the test rather than after, so a test that fails mid-way
    cannot poison the next one.
    """
    reset_rate_limiters()
    clear_screen_cache()
