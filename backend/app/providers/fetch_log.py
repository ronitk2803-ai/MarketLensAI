"""Records every external provider call to `provider_fetch_log`.

Colocated with providers (not services) because logging the IO event belongs
next to where the IO happens (architecture.md dependency rule: providers may
depend on db). Real providers call this from inside their capability methods
once they exist (Build_plan.md §S step 4+).
"""

from sqlalchemy.orm import Session

from app.db.models import ProviderFetchLog


def record_fetch(
    db: Session,
    *,
    provider: str,
    endpoint: str,
    status: str,
    asset_id: int | None = None,
    latency_ms: int | None = None,
    ttl_seconds: int | None = None,
) -> ProviderFetchLog:
    log = ProviderFetchLog(
        provider=provider,
        endpoint=endpoint,
        status=status,
        asset_id=asset_id,
        latency_ms=latency_ms,
        ttl_seconds=ttl_seconds,
    )
    db.add(log)
    db.flush()
    return log
