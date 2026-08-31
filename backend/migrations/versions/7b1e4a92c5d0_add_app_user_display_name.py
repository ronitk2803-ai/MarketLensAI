"""add app_user.display_name

Revision ID: 7b1e4a92c5d0
Revises: 3c29bc20a54b
Create Date: 2026-08-31 00:00:00.000000

Nullable with no backfill, deliberately. Every existing row predates the
`profile` scope, so there is no name on file for any of them, and the only
value that could be invented is one derived from the email local part —
the fabrication SUMMARISER §7 rule 1 rules out. Existing Google users pick a
name up the next time they sign in (link_or_create_user fills a blank one);
password accounts stay NULL and render as their email.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b1e4a92c5d0'
down_revision: Union[str, Sequence[str], None] = '3c29bc20a54b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('app_user', sa.Column('display_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_user', 'display_name')
