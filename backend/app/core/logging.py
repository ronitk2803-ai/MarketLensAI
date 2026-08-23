import logging

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a stdout handler to the root logger.

    Uvicorn's default logging config only sets up the `uvicorn.*` loggers
    and leaves root untouched at WARNING, so every `logging.getLogger(
    __name__)` call in this codebase resolves to a logger with no handler
    and its INFO/ERROR records are discarded. Verified in the container: with
    ENABLE_SCHEDULER=true the scheduler starts (settings parse correctly) but
    neither our own "scheduled" line nor APScheduler's own startup logs reach
    stdout — which would also mean daily_ingestion's per-asset
    `logger.exception` calls vanish, and a nightly job silently failing for
    weeks is exactly the failure this project can least afford.

    Idempotent, and a no-op if something upstream (pytest's caplog, an
    explicit basicConfig in a __main__ block) already installed handlers, so
    it can be called from both the API process and the job entrypoints.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True
