from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env.

    Codename `mlai` — no brand name hard-coded (see product_principles.md).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated list of allowed CORS origins.
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://mlai:mlai@localhost:5432/mlai"

    # Provider credentials — never committed, never sent to the frontend.
    upstox_api_key: str | None = None
    upstox_api_secret: str | None = None
    upstox_redirect_uri: str | None = None

    # Gemini's free tier (rate-limited, no cost) — used for the click-
    # triggered AI company summary. See app/services/company_summary.py for
    # why generation stays inside free-tier limits regardless of traffic.
    gemini_api_key: str | None = None

    # Shared secret gating /admin/* endpoints until a real auth system exists (P1).
    admin_token: str | None = None

    # Signs/verifies JWTs (app/core/security.py, app/services/auth.py). No
    # default — unlike admin_token (which just leaves admin routes
    # unreachable if unset), a missing or weak secret here would let
    # anyone forge a session, so this must fail loudly at startup instead
    # of silently running insecure.
    jwt_secret: str
    # 60 rather than the textbook-minimal 15: there's no silent
    # background refresh yet (a Next.js middleware-based one was
    # considered and rejected — see the P1 auth plan — since Next 16
    # explicitly warns proxy/middleware isn't meant for that), so a
    # shorter TTL would mean re-logging in mid-session. Revisit once
    # reactive refresh-on-401 exists.
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 30

    # Runs app.jobs.daily_ingestion once a day in-process via APScheduler
    # (Build_plan.md §Q MVP default). Off by default so importing app.main
    # for tests, or running a second dev instance, doesn't fire an
    # unattended batch job against the DB. Platforms without a
    # guaranteed always-on process (serverless) should leave this off and
    # trigger `python -m app.jobs.daily_ingestion` from a platform cron
    # job instead — see architecture/claude/Deployment.md.
    enable_scheduler: bool = False
    daily_ingestion_hour_ist: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
