"""seed financials score profile

Revision ID: 1c6a84df5044
Revises: ecf0edc162ae
Create Date: 2026-08-25 22:35:32.381464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c6a84df5044'
down_revision: Union[str, Sequence[str], None] = 'ecf0edc162ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed the "financials" score profile and point the financial-services
    industry at it (Build_plan.md §M).

    Data-only. The weights are inlined rather than imported from
    app.engines.scoring.registry.FINANCIALS_WEIGHTS on purpose: a migration
    has to keep meaning what it meant when it ran, and importing live app
    code would let a later weight change silently rewrite history.

    The industry UPDATE only backfills the rows already seeded by an
    earlier universe sync. app/services/universe.py's INDUSTRY_PROFILE_KEYS
    is what keeps score_profile_key correct from here on, including across
    a reseed — this statement is not the ongoing mechanism.
    """
    op.execute(
        """
        INSERT INTO score_profile (industry_code, version, weights, active, created_at)
        VALUES (
            'financials', 1,
            '{"valuation": 0.25, "earnings_valuation": 0.20, "growth": 0.25,
              "technical_setup": 0.15, "participation": 0.15}'::jsonb,
            true, now()
        )
        ON CONFLICT (industry_code, version) DO NOTHING
        """
    )
    op.execute(
        "UPDATE industry SET score_profile_key = 'financials' WHERE code = 'financial-services'"
    )


def downgrade() -> None:
    """Reverse: unmap the industry first (so nothing resolves to a profile
    that's about to disappear), then drop the profile row.

    Score rows computed against it are deliberately left alone — they're an
    append-only historical record, and deleting them would destroy real
    history to undo a config change. This means the FK from those rows keeps
    the profile alive; the delete is a no-op in that case rather than an
    error, which is the correct outcome.
    """
    op.execute(
        "UPDATE industry SET score_profile_key = 'default' WHERE score_profile_key = 'financials'"
    )
    op.execute(
        """
        DELETE FROM score_profile
        WHERE industry_code = 'financials'
          AND NOT EXISTS (SELECT 1 FROM score WHERE score.profile_id = score_profile.id)
        """
    )
