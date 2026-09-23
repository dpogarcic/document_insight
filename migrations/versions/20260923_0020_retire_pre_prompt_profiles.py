"""Retire the reranker and generator profiles seeded before system_prompt was required.

Revision ID: 20260923_0020
Revises: 20260923_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0020"
down_revision: str | None = "20260923_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seeded by 20260921_0009 before RerankingConfiguration/GenerationConfiguration required
# system_prompt. 20260922_0011 replaced them with profiled successors and moved the active
# query pointer, but left these two selectable, so they still crash any query that resolves
# them (missing required system_prompt field) instead of being excluded from selection.
_RANKER_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000015"
_GENERATOR_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000016"


def upgrade() -> None:
    """Mark the pre-prompt reranker and generator profiles retired."""
    op.execute(
        sa.text("""
            UPDATE capability_profiles SET status = 'retired'
            WHERE id IN (CAST(:ranker AS uuid), CAST(:generator AS uuid))
        """).bindparams(ranker=_RANKER_PROFILE_ID, generator=_GENERATOR_PROFILE_ID)
    )


def downgrade() -> None:
    """Restore the pre-prompt profiles to validated status."""
    op.execute(
        sa.text("""
            UPDATE capability_profiles SET status = 'validated'
            WHERE id IN (CAST(:ranker AS uuid), CAST(:generator AS uuid))
        """).bindparams(ranker=_RANKER_PROFILE_ID, generator=_GENERATOR_PROFILE_ID)
    )
