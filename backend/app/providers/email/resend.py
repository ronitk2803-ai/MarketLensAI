"""Transactional email via Resend's REST API.

The only outbound-email path in the app. Used for the two things that have
to prove someone controls an address: the sign-up verification code and the
password-reset code (app/services/auth_codes.py).

**Testing-mode gotcha, and the first thing to check when "the email never
arrived":** until a domain is verified at resend.com/domains, the default
`onboarding@resend.dev` sender will ONLY deliver to the address that owns
the Resend account. Every other recipient gets a 403 whose message says so.
That is a configuration state, not a bug, and `send` translates it into a
message naming the fix rather than a bare status code.

To confirm which state the key is in:

    curl -s -o /dev/null -w '%{http_code}\n' -X POST https://api.resend.com/emails \
      -H "Authorization: Bearer $RESEND_API_KEY" -H 'Content-Type: application/json' \
      -d '{"from":"onboarding@resend.dev","to":["SOMEONE-ELSE@example.com"],
           "subject":"probe","text":"probe"}'

403 means testing mode (verify a domain). 401 means the key is wrong. 200
means a domain is verified and delivery is unrestricted.
"""

import time

import httpx

from app.providers.errors import ProviderError

API_URL = "https://api.resend.com/emails"

# Deliberately far tighter than gemini_summary.py's 45s budget, and the
# difference is not arbitrary. That one is a deliberate button click on a
# page where the user is already watching a spinner. This one sits on the
# sign-up path, holds one of the threadpool's ~40 workers for its whole
# duration (every route here is a sync `def`), and is calling an endpoint
# that only enqueues — a healthy Resend response is ~200ms, not 20s. A
# generous budget here means a handful of stalled signups can starve the
# whole API, including /health.
_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.0
_TOTAL_DEADLINE_SECONDS = 12.0
_CONNECT_TIMEOUT = 3.0
_READ_TIMEOUT = 8.0


class ResendEmailProvider:
    """Thin wrapper over the REST API — no SDK, same style as
    app/providers/ai/gemini_summary.py."""

    name = "resend"

    def __init__(
        self, api_key: str, *, from_email: str, client: httpx.Client | None = None
    ) -> None:
        self._api_key = api_key
        self._from_email = from_email
        self._client = client

    def send(
        self, *, to: str, subject: str, text: str, idempotency_key: str | None = None
    ) -> str:
        """Returns Resend's message id. Raises ProviderError on any failure.

        `idempotency_key` should be the auth_code row's id: if a network
        retry fires after Resend already accepted the first attempt, this
        stops the recipient getting two codes for one request.
        """
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=3.0, pool=3.0
            )
        )
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        deadline = time.monotonic() + _TOTAL_DEADLINE_SECONDS
        try:
            last_error: ProviderError | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                remaining = deadline - time.monotonic()
                if attempt > 1 and remaining <= 0:
                    break
                try:
                    response = client.post(
                        API_URL,
                        headers=headers,
                        json={
                            "from": self._from_email,
                            "to": [to],
                            "subject": subject,
                            "text": text,
                        },
                        timeout=httpx.Timeout(
                            connect=_CONNECT_TIMEOUT,
                            read=min(_READ_TIMEOUT, max(remaining, 1.0)),
                            write=3.0,
                            pool=3.0,
                        ),
                    )
                except httpx.HTTPError as error:
                    last_error = ProviderError(
                        "resend", f"request failed: {error}", retryable=True
                    )
                    if attempt < _MAX_ATTEMPTS:
                        time.sleep(_RETRY_DELAY_SECONDS)
                        continue
                    raise last_error from error

                if response.status_code == 200:
                    message_id = response.json().get("id")
                    if not message_id:
                        raise ProviderError("resend", "accepted but returned no message id")
                    return str(message_id)

                last_error = _error_for(response)
                if last_error.retryable and attempt < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_SECONDS)
                    continue
                raise last_error

            assert last_error is not None
            raise last_error
        finally:
            if owns_client:
                client.close()


def _error_for(response: httpx.Response) -> ProviderError:
    """Resend's errors are `{statusCode, name, message}`."""
    try:
        body = response.json()
        name = str(body.get("name", ""))
        message = str(body.get("message", "")) or response.text[:300]
    except ValueError:
        name, message = "", response.text[:300]

    # The single most likely failure on a fresh account, and the one that
    # looks least like a configuration problem from the outside: the send
    # "succeeds" for the developer testing with their own address and 403s
    # for literally everyone else. Branch on the status too, since `name`
    # is also "validation_error" for ordinary 400s.
    if response.status_code == 403 and name == "validation_error":
        return ProviderError(
            "resend",
            "Resend is in testing mode: it will only deliver to the address that "
            "owns the Resend account. Verify a domain at resend.com/domains and "
            f"point RESEND_FROM_EMAIL at an address on it. Resend said: {message}",
        )

    # A quota is not a rate limit — retrying a daily/monthly quota failure
    # inside one request just spends the budget again for the same answer.
    retryable = response.status_code >= 500 or (
        response.status_code == 429 and "quota" not in name
    )
    return ProviderError(
        "resend",
        f"send failed: {response.status_code} {name}: {message}",
        retryable=retryable,
    )
