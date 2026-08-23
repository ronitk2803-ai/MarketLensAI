"""Upstox access-token lifecycle (Build_plan.md §G, decision on token strategy).

Upstox's access token expires daily around 03:30 IST and there is no
refresh-token flow. Getting a new one requires a human to complete Upstox's
own login page once and hand us the resulting one-time authorization code
via `POST /admin/upstox/token` (app/api/v1/admin.py) — this server never
sees or stores a password, PIN, or TOTP seed. If a day's token is missing,
NSE Bhavcopy (auth-free) remains the guaranteed EOD spine.

In-memory, single-process state — sufficient for the MVP's single backend
instance; swap for a DB-backed store later without changing this interface.
"""

import datetime as dt

import httpx

from app.core.config import get_settings
from app.providers.errors import ProviderError

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_EXPIRY_HOUR_IST = 3
_EXPIRY_MINUTE_IST = 30

TOKEN_EXCHANGE_URL = "https://api.upstox.com/v2/login/authorization/token"


def _next_expiry(obtained_at: dt.datetime) -> dt.datetime:
    obtained_at = obtained_at.astimezone(IST)
    expiry_today = obtained_at.replace(
        hour=_EXPIRY_HOUR_IST, minute=_EXPIRY_MINUTE_IST, second=0, microsecond=0
    )
    if obtained_at < expiry_today:
        return expiry_today
    return expiry_today + dt.timedelta(days=1)


class UpstoxTokenManager:
    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at: dt.datetime | None = None

    def set_token(self, access_token: str, obtained_at: dt.datetime | None = None) -> None:
        obtained_at = obtained_at or dt.datetime.now(IST)
        self._access_token = access_token
        self._expires_at = _next_expiry(obtained_at)

    def get_token(self) -> str:
        if self._access_token is None or self._expires_at is None:
            raise ProviderError(
                "upstox", "no access token set; POST a fresh code to /admin/upstox/token"
            )
        if dt.datetime.now(IST) >= self._expires_at:
            raise ProviderError(
                "upstox", "access token expired; POST a fresh code to /admin/upstox/token"
            )
        return self._access_token

    def is_valid(self) -> bool:
        try:
            self.get_token()
        except ProviderError:
            return False
        return True


token_manager = UpstoxTokenManager()


def exchange_code_for_token(code: str, *, client: httpx.Client | None = None) -> str:
    """Redeem a one-time authorization `code` (from the user's own Upstox
    login redirect) for an access token. This is Upstox's documented,
    sanctioned OAuth token endpoint — no credentials pass through us."""
    settings = get_settings()
    has_creds = (
        settings.upstox_api_key and settings.upstox_api_secret and settings.upstox_redirect_uri
    )
    if not has_creds:
        raise ProviderError("upstox", "UPSTOX_API_KEY/API_SECRET/REDIRECT_URI not configured")

    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        response = client.post(
            TOKEN_EXCHANGE_URL,
            data={
                "code": code,
                "client_id": settings.upstox_api_key,
                "client_secret": settings.upstox_api_secret,
                "redirect_uri": settings.upstox_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise ProviderError(
            "upstox", f"token exchange failed: {response.status_code} {response.text}"
        )

    access_token = response.json().get("access_token")
    if not access_token:
        raise ProviderError(
            "upstox", f"token exchange response missing access_token: {response.text}"
        )
    return access_token
