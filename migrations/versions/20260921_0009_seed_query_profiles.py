"""Seed immutable query profiles and their cohort associations.

Revision ID: 20260921_0009
Revises: 20260921_0008
"""
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0009"
down_revision: str | None = "20260921_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Query profile IDs
_QUERY_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000051"
_LEXICAL_COHORT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000052"
_EMBEDDING_COHORT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000053"
_ACTIVE_QUERY_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000054"
_QUERY_ACTIVATION_ID = "0b91a2a8-7f3c-45d9-8d99-000000000055"


def upgrade() -> None:
    """Seed query profile data."""
    # Insert query profile
    op.execute(
        sa.text("""
            INSERT INTO query_profiles (id, reranker_profile_id, generation_profile_id, retrieval_snapshot_id, created_at)
            VALUES (CAST(:id AS uuid), CAST(:reranker_profile_id AS uuid), CAST(:generation_profile_id AS uuid), CAST(:retrieval_snapshot_id AS uuid), CURRENT_TIMESTAMP)
        """).bindparams(
            id=_QUERY_PROFILE_ID,
            reranker_profile_id="0b91a2a8-7f3c-45d9-8d99-000000000013",  # Lexical profile ID
            generation_profile_id="0b91a2a8-7f3c-45d9-8d99-000000000014",  # Embedding profile ID
            retrieval_snapshot_id="0b91a2a8-7f3c-45d9-8d99-000000000003",  # Lexical snapshot ID
        )
    )
    
    # Insert lexical cohort
    op.execute(
        sa.text("""
            INSERT INTO query_profile_lexical_cohorts (query_profile_id, lexical_profile_id)
            VALUES (CAST(:query_profile_id AS uuid), CAST(:lexical_profile_id AS uuid))
        """).bindparams(
            query_profile_id=_QUERY_PROFILE_ID,
            lexical_profile_id="0b91a2a8-7f3c-45d9-8d99-000000000013",  # Lexical profile ID
        )
    )
    
    # Insert embedding cohort
    op.execute(
        sa.text("""
            INSERT INTO query_profile_embedding_cohorts (query_profile_id, embedding_profile_id)
            VALUES (CAST(:query_profile_id AS uuid), CAST(:embedding_profile_id AS uuid))
        """).bindparams(
            query_profile_id=_QUERY_PROFILE_ID,
            embedding_profile_id="0b91a2a8-7f3c-45d9-8d99-000000000014",  # Embedding profile ID
        )
    )

    # Insert active query profile
    op.execute(
        sa.text("""
            INSERT INTO active_profiles (id, scope, profile_kind, query_profile_id, revision)
            VALUES (CAST(:id AS uuid), 'platform', 'query', CAST(:profile_id AS uuid), 1)
        """).bindparams(id=_ACTIVE_QUERY_PROFILE_ID, profile_id=_QUERY_PROFILE_ID)
    )

    # Insert query profile activation
    op.execute(
        sa.text("""
            INSERT INTO profile_activations (id, scope, profile_kind, new_profile_id, reason, active_profile_revision)
            VALUES (CAST(:id AS uuid), 'platform', 'query', CAST(:profile_id AS uuid), 'initial explicit baseline', 1)
        """).bindparams(id=_QUERY_ACTIVATION_ID, profile_id=_QUERY_PROFILE_ID)
    )


def downgrade() -> None:
    """Remove query profile data."""
    op.execute(
        sa.text("DELETE FROM profile_activations WHERE id = CAST(:id AS uuid)").bindparams(id=_QUERY_ACTIVATION_ID)
    )
    op.execute(
        sa.text("DELETE FROM active_profiles WHERE id = CAST(:id AS uuid)").bindparams(id=_ACTIVE_QUERY_PROFILE_ID)
    )
    op.execute(
        sa.text("DELETE FROM query_profile_embedding_cohorts WHERE query_profile_id = CAST(:id AS uuid)").bindparams(id=_QUERY_PROFILE_ID)
    )
    op.execute(
        sa.text("DELETE FROM query_profile_lexical_cohorts WHERE query_profile_id = CAST(:id AS uuid)").bindparams(id=_QUERY_PROFILE_ID)
    )
    op.execute(
        sa.text("DELETE FROM query_profiles WHERE id = CAST(:id AS uuid)").bindparams(id=_QUERY_PROFILE_ID)
    )
