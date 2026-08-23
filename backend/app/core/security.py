from fastapi import Header, HTTPException

from app.core.config import get_settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate for admin-only endpoints (Build_plan.md §P: admin endpoints authn+authz gated).

    P0 has no user auth system yet, so this is a shared-secret header check
    against `ADMIN_TOKEN` rather than a full auth dependency.
    """
    settings = get_settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="unauthorized")
