"""add holding broker

Revision ID: ecf0edc162ae
Revises: 8efdabb8a078
Create Date: 2026-08-25 18:41:20.038814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecf0edc162ae'
down_revision: Union[str, Sequence[str], None] = '8efdabb8a078'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Repurpose Holding.source ("manual"|"csv") into Holding.broker
    ("manual"|"zerodha"|"upstox") and move uniqueness from
    (user_id, asset_id) to (user_id, asset_id, broker) — see Holding's
    docstring in app/db/models.py for why (multi-broker consolidation).

    Added nullable first so the backfill has something to fill in before
    the NOT NULL is enforced. The only existing source="csv" rows in this
    pre-launch app are the author's own Zerodha-shaped test imports, so
    backfilling every non-manual row to "zerodha" is accurate for real
    data, not just a placeholder.
    """
    op.add_column('holding', sa.Column('broker', sa.String(), nullable=True))
    op.execute(
        "UPDATE holding SET broker = CASE WHEN source = 'manual' THEN 'manual' ELSE 'zerodha' END"
    )
    op.alter_column('holding', 'broker', nullable=False)
    op.drop_constraint(op.f('uq_holding_user_asset'), 'holding', type_='unique')
    op.create_unique_constraint('uq_holding_user_asset_broker', 'holding', ['user_id', 'asset_id', 'broker'])
    op.drop_column('holding', 'source')


def downgrade() -> None:
    """Reverse of upgrade(): both "zerodha" and "upstox" collapse back to
    the old "csv" value — lossy (which broker a lot came from is lost),
    but the correct inverse of the forward backfill's own imprecision."""
    op.add_column('holding', sa.Column('source', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.execute(
        "UPDATE holding SET source = CASE WHEN broker = 'manual' THEN 'manual' ELSE 'csv' END"
    )
    op.alter_column('holding', 'source', nullable=False)
    op.drop_constraint('uq_holding_user_asset_broker', 'holding', type_='unique')
    op.create_unique_constraint(op.f('uq_holding_user_asset'), 'holding', ['user_id', 'asset_id'], postgresql_nulls_not_distinct=False)
    op.drop_column('holding', 'broker')
