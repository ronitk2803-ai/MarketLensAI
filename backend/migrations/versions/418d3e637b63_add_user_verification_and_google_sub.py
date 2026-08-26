"""add user verification and google sub

Revision ID: 418d3e637b63
Revises: e69473ff3e99
Create Date: 2026-08-26 23:12:47.445492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '418d3e637b63'
down_revision: Union[str, Sequence[str], None] = 'e69473ff3e99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'app_user', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('app_user', sa.Column('google_sub', sa.String(), nullable=True))
    # Google-only accounts have no password at all. See AppUser's docstring
    # for why this is a real NULL rather than a sentinel "unusable hash".
    op.alter_column('app_user', 'hashed_password', existing_type=sa.VARCHAR(), nullable=True)
    op.create_unique_constraint('uq_app_user_google_sub', 'app_user', ['google_sub'])

    # Grandfather every account that predates verification. Without this,
    # the moment the verified gate lands (a later commit) every existing
    # user is locked out of saving anything, with no way to fix it except
    # asking each of them to re-verify an address they already use.
    # Deliberately here rather than in the gate's own migration: this way
    # the backfill is deployed and proven before anything depends on it,
    # instead of both landing together where a half-applied deploy locks
    # out live users.
    op.execute("UPDATE app_user SET email_verified_at = created_at")


def downgrade() -> None:
    """Not reversible.

    Restoring NOT NULL on hashed_password fails outright if any Google-only
    account exists, and there is no correct value to invent for one — the
    account genuinely has no password. Dropping those rows to make the
    downgrade succeed would silently delete real users.

    To roll this back, decide the policy first (delete Google-only accounts,
    or give them a password-reset invitation), apply it by hand, then drop
    the columns.
    """
    raise NotImplementedError(
        "irreversible: hashed_password cannot be made NOT NULL again while "
        "Google-only accounts exist — see this migration's downgrade docstring"
    )
