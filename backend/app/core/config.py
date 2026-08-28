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

    # Resend (transactional email) — the verification and password-reset
    # codes. Optional like every other provider credential: unset simply
    # means those flows return a 502 naming the missing setting, rather
    # than the app refusing to boot for deployments that don't use them.
    # NOTE: until a domain is verified at resend.com/domains, the default
    # onboarding@resend.dev sender only delivers to the Resend account
    # owner's own address — see app/providers/email/resend.py.
    resend_api_key: str | None = None
    resend_from_email: str = "MarketLens AI <onboarding@resend.dev>"

    # Google OAuth ("Sign in with Google"). Entirely separate from the
    # Upstox OAuth above, which is a market-data concern and never touches
    # a user account (Build_plan.md §G).
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must match a redirect URI registered in the Google Cloud console
    # EXACTLY, and differs per environment — :3000 bare-metal dev, :3100
    # for the prod container. Held here rather than in the frontend so the
    # value sent in the authorize URL and the one sent in the token
    # exchange cannot drift apart, which Google rejects with a famously
    # unhelpful error.
    google_redirect_uri: str | None = None

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

    # Whether to trust X-Forwarded-For for rate-limit IP keying (app/core/
    # rate_limit.py). Same shape as frontend/lib/auth-cookies.ts's
    # COOKIE_SECURE: explicit, env-driven, safe by default. False locally
    # and in docker-compose.prod.yml (no reverse proxy there — direct port
    # exposure), true only on a real host (Render/Fly) where an edge proxy
    # actually sits in front — trusting the header with nothing in front to
    # set it truthfully would let any caller hand-pick their own rate-limit
    # key.
    trust_forwarded_for: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
