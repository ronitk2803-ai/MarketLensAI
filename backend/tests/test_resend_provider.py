import httpx
import pytest

from app.providers.email import resend as resend_module
from app.providers.email.resend import ResendEmailProvider
from app.providers.errors import ProviderError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry backoff must not make the suite slow; elapsed time stays ~0 so
    the wall-clock deadline never trips during a test."""
    monkeypatch.setattr(resend_module.time, "sleep", lambda _seconds: None)


def _provider(handler: object) -> ResendEmailProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return ResendEmailProvider(
        "re_test_key", from_email="test@example.com", client=client
    )


def test_send_returns_the_message_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer re_test_key"
        return httpx.Response(200, json={"id": "msg-123"})

    assert _provider(handler).send(to="a@b.com", subject="s", text="t") == "msg-123"


def test_send_passes_the_idempotency_key_through() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("Idempotency-Key", "")
        return httpx.Response(200, json={"id": "msg-1"})

    _provider(handler).send(to="a@b.com", subject="s", text="t", idempotency_key="42")

    assert seen["key"] == "42"


def test_testing_mode_403_names_the_fix_and_does_not_retry() -> None:
    """The single most likely failure on a fresh Resend account, and the one
    that looks least like a configuration problem: it works for the
    developer's own address and 403s for everyone else. A bare status code
    here reads as a bug in our code."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            403,
            json={
                "statusCode": 403,
                "name": "validation_error",
                "message": (
                    "You can only send testing emails to your own email address "
                    "(owner@example.com)."
                ),
            },
        )

    with pytest.raises(ProviderError) as error:
        _provider(handler).send(to="someone@else.com", subject="s", text="t")

    assert "resend.com/domains" in str(error.value)
    assert "RESEND_FROM_EMAIL" in str(error.value)
    assert error.value.retryable is False
    assert calls["n"] == 1  # not retried — retrying cannot change the answer


def test_a_plain_400_validation_error_is_not_mistaken_for_testing_mode() -> None:
    """`name` is "validation_error" for ordinary 400s too, which is why the
    testing-mode branch keys on the status as well."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"statusCode": 400, "name": "validation_error", "message": "bad to"}
        )

    with pytest.raises(ProviderError) as error:
        _provider(handler).send(to="not-an-email", subject="s", text="t")

    assert "resend.com/domains" not in str(error.value)
    assert "bad to" in str(error.value)


def test_a_bad_api_key_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            401, json={"statusCode": 401, "name": "missing_api_key", "message": "nope"}
        )

    with pytest.raises(ProviderError):
        _provider(handler).send(to="a@b.com", subject="s", text="t")

    assert calls["n"] == 1


def test_a_5xx_is_retried_then_raised() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            503, json={"statusCode": 503, "name": "service_unavailable", "message": "later"}
        )

    with pytest.raises(ProviderError) as error:
        _provider(handler).send(to="a@b.com", subject="s", text="t")

    assert error.value.retryable is True
    assert calls["n"] == 2  # _MAX_ATTEMPTS


def test_a_rate_limit_retries_but_a_quota_does_not() -> None:
    """Retrying a rate limit inside one request can succeed; retrying an
    exhausted daily quota just spends the budget again for the same answer."""
    rate_calls = {"n": 0}
    quota_calls = {"n": 0}

    def rate_handler(request: httpx.Request) -> httpx.Response:
        rate_calls["n"] += 1
        return httpx.Response(
            429, json={"statusCode": 429, "name": "rate_limit_exceeded", "message": "slow"}
        )

    def quota_handler(request: httpx.Request) -> httpx.Response:
        quota_calls["n"] += 1
        return httpx.Response(
            429, json={"statusCode": 429, "name": "daily_quota_exceeded", "message": "done"}
        )

    with pytest.raises(ProviderError):
        _provider(rate_handler).send(to="a@b.com", subject="s", text="t")
    with pytest.raises(ProviderError) as quota_error:
        _provider(quota_handler).send(to="a@b.com", subject="s", text="t")

    assert rate_calls["n"] == 2
    assert quota_calls["n"] == 1
    assert quota_error.value.retryable is False


def test_a_network_error_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ProviderError) as error:
        _provider(handler).send(to="a@b.com", subject="s", text="t")

    assert error.value.retryable is True
    assert calls["n"] == 2


def test_a_200_with_no_message_id_is_an_error_not_a_silent_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(ProviderError, match="no message id"):
        _provider(handler).send(to="a@b.com", subject="s", text="t")
