"""Seed immutable query profiles and their cohort associations.

Revision ID: 20260921_0009
Revises: 20260921_0008
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0009"
down_revision: str | None = "20260921_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Capability profile IDs
_RANKER_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000015"
_GENERATOR_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000016"

# Configuration snapshot IDs
_RANKER_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000005"
_GENERATOR_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000006"
_RETRIEVAL_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000007"

# Query profile IDs
_QUERY_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000051"
_LEXICAL_COHORT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000052"
_EMBEDDING_COHORT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000053"
_ACTIVE_QUERY_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000054"
_QUERY_ACTIVATION_ID = "0b91a2a8-7f3c-45d9-8d99-000000000055"


def _fingerprint(configuration: dict) -> str:
    """Create a stable non-secret configuration fingerprint."""
    from hashlib import sha256

    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def upgrade() -> None:
    """Seed query profile data with all required capability profiles."""

    # Insert reranking capability snapshot
    op.execute(
        sa.text("""
            INSERT INTO configuration_snapshots
            (id, capability, schema_version, fingerprint, configuration_json)
            VALUES (CAST(:id AS uuid), :capability, 1, :fingerprint, CAST(:configuration AS jsonb))
        """).bindparams(
            id=_RANKER_SNAPSHOT_ID,
            capability="reranking",
            fingerprint=_fingerprint(
                {
                    "provider": "mistral",
                    "model": "ministral-3b-2512",
                    "configuration_revision": "ministral-3b-2512",
                    "prompt_revision": "llm-rerank-v2",
                    "response_schema_revision": "rerank-scores-v2",
                    "temperature": 0.0,
                    "max_output_tokens": 2048,
                }
            ),
            configuration=json.dumps(
                {
                    "provider": "mistral",
                    "model": "ministral-3b-2512",
                    "configuration_revision": "ministral-3b-2512",
                    "prompt_revision": "llm-rerank-v2",
                    "response_schema_revision": "rerank-scores-v2",
                    "temperature": 0.0,
                    "max_output_tokens": 2048,
                },
                sort_keys=True,
            ),
        )
    )

    # Insert reranking capability profile
    op.execute(
        sa.text("""
            INSERT INTO capability_profiles
            (id, capability, name, configuration_snapshot_id, status)
            VALUES (CAST(:id AS uuid), :capability, :name, CAST(:snapshot_id AS uuid), 'validated')
        """).bindparams(
            id=_RANKER_PROFILE_ID,
            capability="reranking",
            name="ministral-3b-2512-reranker-v2",
            snapshot_id=_RANKER_SNAPSHOT_ID,
        )
    )

    # Insert generation capability snapshot
    op.execute(
        sa.text("""
            INSERT INTO configuration_snapshots
            (id, capability, schema_version, fingerprint, configuration_json)
            VALUES (CAST(:id AS uuid), :capability, 1, :fingerprint, CAST(:configuration AS jsonb))
        """).bindparams(
            id=_GENERATOR_SNAPSHOT_ID,
            capability="generation",
            fingerprint=_fingerprint(
                {
                    "provider": "mistral",
                    "model": "ministral-3b-2512",
                    "configuration_revision": "ministral-3b-2512",
                    "prompt_revision": "grounded-answer-v3",
                    "response_schema_revision": "grounded-answer-indices-v1",
                    "temperature": 0.0,
                    "max_output_tokens": 1024,
                }
            ),
            configuration=json.dumps(
                {
                    "provider": "mistral",
                    "model": "ministral-3b-2512",
                    "configuration_revision": "ministral-3b-2512",
                    "prompt_revision": "grounded-answer-v3",
                    "response_schema_revision": "grounded-answer-indices-v1",
                    "temperature": 0.0,
                    "max_output_tokens": 1024,
                },
                sort_keys=True,
            ),
        )
    )

    # Insert generation capability profile
    op.execute(
        sa.text("""
            INSERT INTO capability_profiles
            (id, capability, name, configuration_snapshot_id, status)
            VALUES (CAST(:id AS uuid), :capability, :name, CAST(:snapshot_id AS uuid), 'validated')
        """).bindparams(
            id=_GENERATOR_PROFILE_ID,
            capability="generation",
            name="ministral-3b-2512-grounded-answer-v3",
            snapshot_id=_GENERATOR_SNAPSHOT_ID,
        )
    )

    # Insert retrieval configuration snapshot
    retrieval_config = {
        "lexical_candidate_limit": 50,
        "vector_candidate_limit": 50,
        "rerank_candidate_limit": 20,
        "rrf_k": 60,
        "entity_match_boost": 0.1,
        "insufficient_evidence_threshold": 0.45,
        "min_citation_score": 0.35,
    }
    op.execute(
        sa.text("""
            INSERT INTO configuration_snapshots
            (id, capability, schema_version, fingerprint, configuration_json)
            VALUES (CAST(:id AS uuid), :capability, 1, :fingerprint, CAST(:configuration AS jsonb))
        """).bindparams(
            id=_RETRIEVAL_SNAPSHOT_ID,
            capability="retrieval",
            fingerprint=_fingerprint(retrieval_config),
            configuration=json.dumps(retrieval_config, sort_keys=True),
        )
    )

    # Insert query profile (fixed to point to correct profiles)
    op.execute(
        sa.text("""
            INSERT INTO query_profiles (id, reranker_profile_id, generation_profile_id, retrieval_snapshot_id, created_at)
            VALUES (CAST(:id AS uuid), CAST(:reranker_profile_id AS uuid), CAST(:generation_profile_id AS uuid), CAST(:retrieval_snapshot_id AS uuid), CURRENT_TIMESTAMP)
        """).bindparams(
            id=_QUERY_PROFILE_ID,
            reranker_profile_id=_RANKER_PROFILE_ID,
            generation_profile_id=_GENERATOR_PROFILE_ID,
            retrieval_snapshot_id=_RETRIEVAL_SNAPSHOT_ID,
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
        sa.text("DELETE FROM profile_activations WHERE id = CAST(:id AS uuid)").bindparams(
            id=_QUERY_ACTIVATION_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM active_profiles WHERE id = CAST(:id AS uuid)").bindparams(
            id=_ACTIVE_QUERY_PROFILE_ID
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM query_profile_embedding_cohorts WHERE query_profile_id = CAST(:id AS uuid)"
        ).bindparams(id=_QUERY_PROFILE_ID)
    )
    op.execute(
        sa.text(
            "DELETE FROM query_profile_lexical_cohorts WHERE query_profile_id = CAST(:id AS uuid)"
        ).bindparams(id=_QUERY_PROFILE_ID)
    )
    op.execute(
        sa.text("DELETE FROM query_profiles WHERE id = CAST(:id AS uuid)").bindparams(
            id=_QUERY_PROFILE_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM capability_profiles WHERE id = CAST(:id AS uuid)").bindparams(
            id=_GENERATOR_PROFILE_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM configuration_snapshots WHERE id = CAST(:id AS uuid)").bindparams(
            id=_GENERATOR_SNAPSHOT_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM capability_profiles WHERE id = CAST(:id AS uuid)").bindparams(
            id=_RANKER_PROFILE_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM configuration_snapshots WHERE id = CAST(:id AS uuid)").bindparams(
            id=_RANKER_SNAPSHOT_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM configuration_snapshots WHERE id = CAST(:id AS uuid)").bindparams(
            id=_RETRIEVAL_SNAPSHOT_ID
        )
    )
