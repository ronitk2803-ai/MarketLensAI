"""Turning a Google identity into a local account.

The linking rule is the highest-stakes logic in the auth system: a mistake
here is full account takeover, not an inconvenience. It is written out
case by case below for that reason.

The attack it defends against is federated account pre-hijacking (USENIX
Security 2022). Registration does not prove control of an address, so:

  1. Attacker registers victim@gmail.com with a password they choose.
  2. They wait, optionally holding a 30-day refresh token.
  3. The victim later clicks "Sign in with Google" as the real owner.
  4. A naive "email matches, so link" rule hands the victim an account
     whose password the attacker knows and whose session they still hold.

Google asserting `email_verified` proves *Google's* user owns the address.
It says nothing about whether the local password was ever proven, which is
why the branch below turns on the state of the EXISTING account rather than
on the Google side.
"""

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthCode
from app.providers.auth.google_oauth import GoogleIdentity
from app.services.auth import revoke_all_refresh_tokens
from app.services.auth_codes import mark_email_verified


def _consume_outstanding_codes(db: Session, user_id: int) -> None:
    """Retires every live verification/reset code for a user.

    A provider that has just asserted `email_verified` supersedes any
    pending proof-of-control challenge, and a live code left over after the
    account's credential state changed is attack surface with no upside.
    """
    (
        db.query(AuthCode)
        .filter(AuthCode.user_id == user_id, AuthCode.consumed_at.is_(None))
        .update({"consumed_at": dt.datetime.now(dt.UTC)}, synchronize_session=False)
    )
    db.flush()


def link_or_create_user(db: Session, identity: GoogleIdentity) -> AppUser:
    """Resolve a Google identity to an AppUser, linking or creating as needed."""
    # Google's address is normalized the same way create_user does, because
    # app_user.email is a plain String with a unique btree — the DB will
    # happily accept a second row differing only in case.
    email = identity.email.strip().lower()

    # 1. Known Google account. Nothing to decide.
    existing = db.query(AppUser).filter_by(google_sub=identity.sub).one_or_none()
    if existing is not None:
        mark_email_verified(db, existing)
        return existing

    by_email = db.query(AppUser).filter_by(email=email).one_or_none()

    # 2. Brand new. No password at all — that's what nullable
    #    hashed_password is for.
    if by_email is None:
        user = AppUser(
            email=email,
            hashed_password=None,
            google_sub=identity.sub,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Two callbacks for the same new address raced past the check
            # above. Re-read rather than 500 — one of them created it.
            db.rollback()
            user = db.query(AppUser).filter_by(email=email).one()
            user.google_sub = identity.sub
            db.flush()
        mark_email_verified(db, user)
        return user

    # 3. The address already has a VERIFIED local account. Both parties have
    #    proven control of it, so linking is safe and the password stays.
    if by_email.email_verified_at is not None:
        by_email.google_sub = identity.sub
        db.flush()
        return by_email

    # 4. The address has an UNVERIFIED local account — the pre-hijacking
    #    case. Someone set a password on an address they never proved they
    #    could read. Link, but destroy everything that unproven registration
    #    established: the password, every session it opened, and any code it
    #    had outstanding. The real owner can add a password back through
    #    /password-reset, which does require reading the inbox.
    by_email.google_sub = identity.sub
    by_email.hashed_password = None
    db.flush()
    revoke_all_refresh_tokens(db, by_email.id)
    _consume_outstanding_codes(db, by_email.id)
    mark_email_verified(db, by_email)
    return by_email
