"""Google OAuth 2.0 / OpenID Connect — user sign-in.

Entirely separate from upstox_token_manager.py in this same package, which
is a *market-data* concern and never touches a user account (Build_plan.md
§G is explicit about not conflating the two).

**No JWT or JWKS handling anywhere here, deliberately.** The authorization
code is exchanged for a token directly with Google over TLS using our own
client secret, then the identity is read from the OIDC userinfo endpoint.
Verifying an ID token's signature would mean pulling in `cryptography`,
fetching and caching Google's JWKS, and getting `aud`/`iss` checks right —
all to re-establish something the direct exchange already guarantees. One
extra ~200ms HTTP call buys the simpler, harder-to-get-wrong version.

The redirect URI must match what is registered in the Google Cloud console
byte for byte. Local dev and the prod container both use
http://localhost:3000/api/auth/google/callback (the container's frontend is
on 3000 too — docker-compose.prod.yml); a hosted deploy adds its own domain
as a second registered URI. It lives in settings so the authorize-URL value
and the token-exchange value can't drift apart. Google permits plain http
only for localhost/127.0.0.1.
"""

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.providers.errors import ProviderError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# `openid email` and nothing more. `profile` would add a name and picture we
# don't display, and access_type=offline would hand us a refresh token we
# discard immediately — both are consent-screen liabilities with no payoff.
SCOPES = "openid email"

_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """The only three things we take from Google.

    Parsed into a typed shape rather than passed around as the raw
    `dict[str, Any]` the API returns, so `email_verified` cannot silently
    become None somewhere downstream and read as falsy.
    """

    sub: str
    email: str
    email_verified: bool


def _require_config() -> tuple[str, str, str]:
    settings = get_settings()
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret
    redirect_uri = settings.google_redirect_uri
    if not (client_id and client_secret and redirect_uri):
        raise ProviderError(
            "google_oauth",
            "GOOGLE_CLIENT_ID/CLIENT_SECRET/REDIRECT_URI not configured",
        )
    return client_id, client_secret, redirect_uri


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
    )


def build_authorize_url(state: str) -> str:
    """The URL to send the browser to.

    Built here rather than in the frontend so the `redirect_uri` sent now
    and the one sent at exchange time come from one value and cannot drift
    — a mismatch is rejected by Google with a notoriously unhelpful error,
    and it fails in the user's browser rather than anywhere we would see.
    """
    client_id, _secret, redirect_uri = _require_config()
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            # Google remembers a previous grant and would otherwise skip
            # the account chooser, which is wrong on a shared machine.
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code(code: str, *, client: httpx.Client | None = None) -> GoogleIdentity:
    """Authorization code -> the signed-in user's identity.

    Raises ProviderError for every failure, including an address Google
    itself has not verified: linking on an unverified Google email would
    let anyone who can create a Google account with a claimed address take
    over the matching local one.
    """
    client_id, client_secret, redirect_uri = _require_config()
    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    try:
        token_response = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_response.status_code != 200:
            raise ProviderError(
                "google_oauth",
                f"token exchange failed: {token_response.status_code} "
                f"{token_response.text[:300]}",
            )
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise ProviderError("google_oauth", "token exchange returned no access_token")

        userinfo_response = client.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_response.status_code != 200:
            raise ProviderError(
                "google_oauth",
                f"userinfo failed: {userinfo_response.status_code} "
                f"{userinfo_response.text[:300]}",
            )
        payload = userinfo_response.json()
    finally:
        if owns_client:
            client.close()

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise ProviderError("google_oauth", "userinfo missing sub or email")

    # `is True`, not truthiness. The field is `email_verified` on this OIDC
    # endpoint; the legacy /oauth2/v1/userinfo called it `verified_email`,
    # and reading the wrong key yields None — which a truthiness check would
    # treat as "unverified" and an `!= False` check would treat as verified.
    # An identity comparison fails loudly for both mistakes, and also
    # rejects the string "false".
    if payload.get("email_verified") is not True:
        raise ProviderError(
            "google_oauth",
            "Google has not verified this email address, so it cannot be used to sign in",
        )

    return GoogleIdentity(sub=str(sub), email=str(email), email_verified=True)
