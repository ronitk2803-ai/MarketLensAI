import datetime as dt
import time

from sqlalchemy.orm import Session

from app.db.models import AppUser, RefreshToken
from app.services.auth import (
    authenticate_user,
    create_user,
    decode_access_token,
    hash_password,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)


def test_hash_password_roundtrips() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"  # never store the raw password
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_create_user_persists_hashed_password(db: Session) -> None:
    user = create_user(db, "  Test@Example.com  ", "a-real-password")

    assert user is not None
    assert user.email == "test@example.com"  # trimmed and lowercased
    assert user.hashed_password != "a-real-password"
    assert db.query(AppUser).filter_by(email="test@example.com").count() == 1


def test_create_user_rejects_duplicate_email(db: Session) -> None:
    create_user(db, "dup@example.com", "password-one")

    result = create_user(db, "dup@example.com", "password-two")

    assert result is None
    assert db.query(AppUser).filter_by(email="dup@example.com").count() == 1


def test_authenticate_user_accepts_correct_password(db: Session) -> None:
    create_user(db, "auth@example.com", "the-real-password")

    user = authenticate_user(db, "auth@example.com", "the-real-password")

    assert user is not None
    assert user.email == "auth@example.com"


def test_authenticate_user_rejects_wrong_password(db: Session) -> None:
    create_user(db, "auth2@example.com", "the-real-password")

    assert authenticate_user(db, "auth2@example.com", "not-the-password") is None


def test_authenticate_user_rejects_unknown_email(db: Session) -> None:
    assert authenticate_user(db, "nobody@example.com", "anything") is None


def test_issue_tokens_access_token_decodes_to_the_right_user(db: Session) -> None:
    user = create_user(db, "tokens@example.com", "password123")
    assert user is not None

    access_token, _refresh_token = issue_tokens(db, user)

    assert decode_access_token(access_token) == user.id


def test_decode_access_token_rejects_garbage() -> None:
    assert decode_access_token("not.a.jwt") is None


def test_rotate_refresh_token_revokes_old_and_issues_new(db: Session) -> None:
    user = create_user(db, "rotate@example.com", "password123")
    assert user is not None
    _access, refresh_token = issue_tokens(db, user)

    rotated = rotate_refresh_token(db, refresh_token)

    assert rotated is not None
    new_access, new_refresh = rotated
    assert new_refresh != refresh_token
    assert decode_access_token(new_access) == user.id
    # The old token is dead — using it again must fail, not just "still work".
    assert rotate_refresh_token(db, refresh_token) is None


def test_rotate_refresh_token_rejects_unknown_token(db: Session) -> None:
    assert rotate_refresh_token(db, "this-token-was-never-issued") is None


def test_rotate_refresh_token_rejects_expired_token(db: Session) -> None:
    user = create_user(db, "expired@example.com", "password123")
    assert user is not None
    _access, refresh_token = issue_tokens(db, user)

    # Force the stored row into the past, same technique the other
    # TTL-staleness tests in this suite use.
    row = db.query(RefreshToken).filter_by(user_id=user.id).one()
    row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db.flush()

    assert rotate_refresh_token(db, refresh_token) is None


def test_revoke_refresh_token_makes_it_unusable(db: Session) -> None:
    user = create_user(db, "revoke@example.com", "password123")
    assert user is not None
    _access, refresh_token = issue_tokens(db, user)

    revoke_refresh_token(db, refresh_token)

    assert rotate_refresh_token(db, refresh_token) is None


def test_revoke_refresh_token_is_a_no_op_for_an_unknown_token(db: Session) -> None:
    revoke_refresh_token(db, "never-issued")  # must not raise


def test_verify_password_is_false_for_an_account_with_no_password() -> None:
    """A Google-only account has hashed_password NULL. This must be a clean
    False, not an exception: PasswordHasher.verify(None, ...) raises
    AttributeError while decoding the hash — before argon2 runs, so no
    argon2 exception class covers it — which would surface as a 500 where
    the caller wanted "wrong credentials"."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


def test_authenticate_user_rejects_an_account_with_no_password(db: Session) -> None:
    user = AppUser(email="googleonly@example.com", hashed_password=None)
    db.add(user)
    db.flush()

    assert authenticate_user(db, "googleonly@example.com", "password123") is None


def test_authenticate_user_costs_the_same_for_known_and_unknown_emails(
    db: Session,
) -> None:
    """Regression: the original `user is None or not verify_password(...)`
    short-circuited, so an unknown address never reached Argon2 and returned
    in ~1ms against ~60ms for a registered one. That timing gap re-enabled
    exactly the account enumeration the deliberately-identical error message
    in app/api/v1/auth.py exists to prevent.

    Asserted as a ratio rather than an absolute, and generously — the point
    is that both paths run one hash, not that a shared CI runner produces
    stable timings."""
    user = create_user(db, "timing@example.com", "password123")
    assert user is not None

    def _elapsed(email: str) -> float:
        start = time.perf_counter()
        authenticate_user(db, email, "the-wrong-password")
        return time.perf_counter() - start

    # Warm up, so first-call import/allocation costs don't land in a sample.
    _elapsed("timing@example.com")

    known = min(_elapsed("timing@example.com") for _ in range(3))
    unknown = min(_elapsed("nosuchuser@example.com") for _ in range(3))

    # Before the fix this ratio was ~60x.
    assert 0.2 < (unknown / known) < 5.0
