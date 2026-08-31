"""Google account linking — the one place an auth bug is takeover.

The scenario each test is named for comes from federated account
pre-hijacking (USENIX Security 2022); see app/services/google_auth.py.
"""

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthCode, RefreshToken
from app.providers.auth.google_oauth import GoogleIdentity
from app.providers.errors import ProviderError
from app.services.auth import hash_password, issue_tokens
from app.services.google_auth import link_or_create_user


def _identity(email: str = "gu@example.com", sub: str = "google-sub-1") -> GoogleIdentity:
    return GoogleIdentity(sub=sub, email=email, email_verified=True)


def test_a_brand_new_address_creates_a_verified_account_with_no_password(
    db: Session,
) -> None:
    user = link_or_create_user(db, _identity())

    assert user.email == "gu@example.com"
    assert user.google_sub == "google-sub-1"
    assert user.hashed_password is None
    assert user.email_verified_at is not None


def test_a_returning_google_account_is_matched_on_sub_not_email(db: Session) -> None:
    """The sub is stable across a Gmail rename; the email is not."""
    first = link_or_create_user(db, _identity(email="renamer@example.com"))
    renamed = link_or_create_user(
        db, GoogleIdentity(sub="google-sub-1", email="new-name@example.com", email_verified=True)
    )

    assert renamed.id == first.id


def test_linking_a_verified_local_account_keeps_its_password(db: Session) -> None:
    """Both parties have proven control of the address, so there is nothing
    to distrust and no reason to lock the user out of password sign-in."""
    existing = AppUser(
        email="verified@example.com",
        hashed_password=hash_password("their-real-password"),
        email_verified_at=dt.datetime.now(dt.UTC),
    )
    db.add(existing)
    db.flush()

    linked = link_or_create_user(db, _identity(email="verified@example.com"))

    assert linked.id == existing.id
    assert linked.google_sub == "google-sub-1"
    assert linked.hashed_password is not None


def test_linking_an_unverified_local_account_destroys_the_unproven_credential(
    db: Session,
) -> None:
    """Account pre-hijacking, the whole reason this branch exists.

    An attacker registers the victim's address (registration proves
    nothing), keeps a 30-day refresh token, and waits. When the real owner
    signs in with Google, a naive "email matches, so link" would hand them
    an account whose password the attacker knows and whose session the
    attacker still holds.

    Google asserting email_verified proves GOOGLE's user owns the address.
    It says nothing about the local password, so the local password and
    everything it opened must go.
    """
    attacker_account = AppUser(
        email="victim@example.com",
        hashed_password=hash_password("attacker-knows-this"),
        email_verified_at=None,
    )
    db.add(attacker_account)
    db.flush()
    _access, attacker_refresh = issue_tokens(db, attacker_account)
    db.add(
        AuthCode(
            user_id=attacker_account.id,
            purpose="verify_email",
            code_hash="whatever",
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10),
        )
    )
    db.flush()

    linked = link_or_create_user(db, _identity(email="victim@example.com"))

    assert linked.id == attacker_account.id
    assert linked.google_sub == "google-sub-1"
    assert linked.email_verified_at is not None
    # The password the attacker set is gone...
    assert linked.hashed_password is None
    # ...their session is revoked...
    token_row = (
        db.query(RefreshToken)
        .filter_by(user_id=attacker_account.id)
        .order_by(RefreshToken.id.desc())
        .first()
    )
    assert token_row is not None and token_row.revoked_at is not None
    assert attacker_refresh  # (the raw token is now useless)
    # ...and any code they had outstanding is dead.
    assert (
        db.query(AuthCode)
        .filter_by(user_id=attacker_account.id, consumed_at=None)
        .count()
        == 0
    )


def test_google_email_is_lowercased_before_lookup(db: Session) -> None:
    """app_user.email is a plain String with a unique btree — the database
    would happily accept a second row differing only in case."""
    existing = AppUser(
        email="mixed@example.com",
        hashed_password=hash_password("pw"),
        email_verified_at=dt.datetime.now(dt.UTC),
    )
    db.add(existing)
    db.flush()

    linked = link_or_create_user(db, _identity(email="  Mixed@Example.COM  "))

    assert linked.id == existing.id


def _exchange_with(
    monkeypatch: pytest.MonkeyPatch, userinfo: dict[str, object]
) -> GoogleIdentity:
    """Drives exchange_code against a stubbed Google.

    Settings are patched on the module rather than through the environment,
    the same way test_company_summary.py does it — CI sets only DATABASE_URL
    and JWT_SECRET, so the real google_* settings are None there and the
    provider would refuse before it ever parsed a response.
    """
    import httpx

    from app.providers.auth import google_oauth
    from app.providers.auth.google_oauth import exchange_code

    class _Settings:
        google_client_id = "cid"
        google_client_secret = "secret"
        google_redirect_uri = "http://localhost:3000/api/auth/google/callback"

    monkeypatch.setattr(google_oauth, "get_settings", lambda: _Settings())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json=userinfo)

    return exchange_code("code", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_an_unverified_google_address_never_reaches_the_linker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforced in the provider, before any account is touched: linking on
    an address Google itself hasn't verified would let anyone who can make a
    Google account claiming an address take over the matching local one."""
    with pytest.raises(ProviderError, match="not verified"):
        _exchange_with(
            monkeypatch, {"sub": "s", "email": "x@example.com", "email_verified": False}
        )


def test_a_string_false_is_not_mistaken_for_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`is True`, not truthiness — the non-empty string "false" is truthy."""
    with pytest.raises(ProviderError, match="not verified"):
        _exchange_with(
            monkeypatch, {"sub": "s", "email": "x@example.com", "email_verified": "false"}
        )


def test_a_missing_email_verified_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy /oauth2/v1/userinfo endpoint called this field
    `verified_email`. Reading the wrong key yields None, which an
    `!= False` check would have treated as verified."""
    with pytest.raises(ProviderError, match="not verified"):
        _exchange_with(
            monkeypatch, {"sub": "s", "email": "x@example.com", "verified_email": True}
        )


def test_a_verified_identity_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.providers.auth import google_oauth
    from app.providers.auth.google_oauth import exchange_code

    class _Settings:
        google_client_id = "cid"
        google_client_secret = "secret"
        google_redirect_uri = "http://localhost:3000/api/auth/google/callback"

    monkeypatch.setattr(google_oauth, "get_settings", lambda: _Settings())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(
            200, json={"sub": "abc", "email": "Real@Example.com", "email_verified": True}
        )

    identity = exchange_code("code", client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert identity.sub == "abc"
    assert identity.email == "Real@Example.com"
    assert identity.email_verified is True


def _named(
    name: str | None, sub: str = "google-sub-1", email: str = "gu@example.com"
) -> GoogleIdentity:
    return GoogleIdentity(sub=sub, email=email, email_verified=True, name=name)


def test_a_new_google_account_stores_the_name_google_supplied(db: Session) -> None:
    user = link_or_create_user(db, _named("Asha Nair", sub="named", email="named@example.com"))

    assert user.display_name == "Asha Nair"


def test_an_account_google_gave_no_name_for_keeps_a_null_display_name(db: Session) -> None:
    """`profile` can be declined at the consent screen independently of
    `email`. The fallback is the address itself — never a name derived from
    it, which would be fabricating a fact about a person."""
    user = link_or_create_user(db, _identity())

    assert user.display_name is None


def test_a_returning_sign_in_backfills_a_name_onto_an_older_account(db: Session) -> None:
    """Accounts created before the `profile` scope was requested have no
    name on file; the next sign-in is the only chance to pick one up."""
    first = link_or_create_user(db, _identity(email="backfill@example.com"))
    assert first.display_name is None

    returning = link_or_create_user(db, _named("Ravi Menon", email="backfill@example.com"))

    assert returning.id == first.id
    assert returning.display_name == "Ravi Menon"


def test_a_name_already_on_file_is_never_overwritten_by_google(db: Session) -> None:
    """Guards the future account-settings field: a re-login must not revert
    a name the user chose for themselves back to their Google profile's."""
    user = link_or_create_user(db, _named("First Name", sub="keeper", email="keeper@example.com"))
    user.display_name = "What They Chose"
    db.flush()

    returning = link_or_create_user(
        db, _named("First Name", sub="keeper", email="keeper@example.com")
    )

    assert returning.display_name == "What They Chose"


def test_the_name_google_supplies_is_read_off_userinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _exchange_with(
        monkeypatch,
        {"sub": "s", "email": "x@example.com", "email_verified": True, "name": "Priya Iyer"},
    )

    assert identity.name == "Priya Iyer"


def test_a_blank_name_is_read_as_absent_not_as_an_empty_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whitespace-only name would render as an empty header slot, which
    reads as a broken page rather than as "no name on file"."""
    identity = _exchange_with(
        monkeypatch,
        {"sub": "s", "email": "x@example.com", "email_verified": True, "name": "   "},
    )

    assert identity.name is None


def test_userinfo_without_a_name_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`profile` is a separate consent checkbox from `email`."""
    identity = _exchange_with(
        monkeypatch, {"sub": "s", "email": "x@example.com", "email_verified": True}
    )

    assert identity.name is None
