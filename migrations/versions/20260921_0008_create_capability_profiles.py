"""Create immutable capability profiles and profile-linked index generations.

Revision ID: 20260921_0008
Revises: 20260921_0007
"""

import json
from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0008"
down_revision: str | None = "20260921_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NER_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000001"
_CHUNKING_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000002"
_LEXICAL_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000003"
_EMBEDDING_SNAPSHOT_ID = "0b91a2a8-7f3c-45d9-8d99-000000000004"
_NER_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000011"
_CHUNKING_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000012"
_LEXICAL_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000013"
_EMBEDDING_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000014"
_INGESTION_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000021"
_ACTIVE_PROFILE_ID = "0b91a2a8-7f3c-45d9-8d99-000000000031"
_ACTIVATION_ID = "0b91a2a8-7f3c-45d9-8d99-000000000041"


class Vector(sa.types.UserDefinedType[object]):
    """Compile pgvector's dimension-agnostic column type in this migration."""

    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        """Return PostgreSQL's pgvector type name."""
        return "VECTOR"


def _fingerprint(configuration: dict[str, object]) -> str:
    """Create a stable non-secret configuration fingerprint."""
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def upgrade() -> None:
    """Create profile/versioning tables and seed the explicit initial baseline."""
    op.create_table(
        "configuration_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability IN ('ner', 'chunking', 'lexical', 'embedding', 'reranking', 'generation', 'retrieval')",
            name="valid_capability",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability", "fingerprint"),
    )
    op.create_table(
        "capability_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("configuration_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability IN ('ner', 'chunking', 'lexical', 'embedding', 'reranking', 'generation', 'retrieval')",
            name="valid_capability",
        ),
        sa.CheckConstraint("status IN ('draft', 'validated', 'retired')", name="valid_status"),
        sa.ForeignKeyConstraint(
            ["configuration_snapshot_id"], ["configuration_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability", "name"),
    )
    op.create_table(
        "ingestion_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ner_profile_id", sa.Uuid(), nullable=False),
        sa.Column("chunking_profile_id", sa.Uuid(), nullable=False),
        sa.Column("lexical_profile_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_profile_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ner_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["chunking_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["lexical_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["embedding_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "query_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reranker_profile_id", sa.Uuid(), nullable=False),
        sa.Column("generation_profile_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reranker_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generation_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_snapshot_id"], ["configuration_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "query_profile_lexical_cohorts",
        sa.Column("query_profile_id", sa.Uuid(), nullable=False),
        sa.Column("lexical_profile_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["query_profile_id"], ["query_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["lexical_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("query_profile_id", "lexical_profile_id"),
    )
    op.create_table(
        "query_profile_embedding_cohorts",
        sa.Column("query_profile_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_profile_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["query_profile_id"], ["query_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["embedding_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("query_profile_id", "embedding_profile_id"),
    )
    op.create_table(
        "active_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(120), nullable=False),
        sa.Column("profile_kind", sa.String(32), nullable=False),
        sa.Column("ingestion_profile_id", sa.Uuid()),
        sa.Column("query_profile_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("profile_kind IN ('ingestion', 'query')", name="valid_profile_kind"),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint(
            "(profile_kind = 'ingestion' AND ingestion_profile_id IS NOT NULL AND query_profile_id IS NULL) "
            "OR (profile_kind = 'query' AND query_profile_id IS NOT NULL AND ingestion_profile_id IS NULL)",
            name="matching_profile_kind",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_profile_id"], ["ingestion_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["query_profile_id"], ["query_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "profile_kind"),
    )
    op.create_table(
        "profile_activations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(120), nullable=False),
        sa.Column("profile_kind", sa.String(32), nullable=False),
        sa.Column("previous_profile_id", sa.Uuid()),
        sa.Column("new_profile_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("active_profile_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "index_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_profile_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("chunking_completed_at", sa.DateTime(timezone=True)),
        sa.Column("lexical_indexed_at", sa.DateTime(timezone=True)),
        sa.Column("embedding_completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('building', 'ready', 'failed', 'superseded')", name="valid_status"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_profile_id"], ["ingestion_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "ingestion_profile_id"),
    )
    op.create_index(op.f("ix_index_generations_tenant_id"), "index_generations", ["tenant_id"])
    op.create_index(
        op.f("ix_index_generations_document_version_id"),
        "index_generations",
        ["document_version_id"],
    )
    op.add_column("processing_jobs", sa.Column("ingestion_profile_id", sa.Uuid()))
    op.add_column("processing_jobs", sa.Column("index_generation_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_processing_jobs_ingestion_profile_id_ingestion_profiles",
        "processing_jobs",
        "ingestion_profiles",
        ["ingestion_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_processing_jobs_index_generation_id_index_generations",
        "processing_jobs",
        "index_generations",
        ["index_generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("chunks", sa.Column("index_generation_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_chunks_index_generation_id_index_generations",
        "chunks",
        "index_generations",
        ["index_generation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_chunks_index_generation_id"), "chunks", ["index_generation_id"])
    op.drop_constraint(op.f("uq_chunks_document_version_id"), "chunks", type_="unique")
    op.create_unique_constraint(
        "uq_chunks_index_generation_ordinal", "chunks", ["index_generation_id", "ordinal"]
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_profile_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["embedding_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", "embedding_profile_id"),
    )
    op.create_index(op.f("ix_chunk_embeddings_chunk_id"), "chunk_embeddings", ["chunk_id"])
    op.create_index(
        op.f("ix_chunk_embeddings_embedding_profile_id"),
        "chunk_embeddings",
        ["embedding_profile_id"],
    )

    snapshots = (
        (
            _NER_SNAPSHOT_ID,
            "ner",
            {
                "provider": "spacy",
                "english_model": "en_core_web_sm",
                "croatian_model": "hr_core_news_sm",
                "model_revision": "3.8.0",
            },
        ),
        (
            _CHUNKING_SNAPSHOT_ID,
            "chunking",
            {
                "implementation": "page_window",
                "implementation_revision": "1",
                "max_chars": 1000,
                "overlap_chars": 150,
            },
        ),
        (
            _LEXICAL_SNAPSHOT_ID,
            "lexical",
            {
                "implementation": "postgres_fts",
                "configuration": "simple",
                "implementation_revision": "1",
            },
        ),
        (
            _EMBEDDING_SNAPSHOT_ID,
            "embedding",
            {
                "provider": "mistral",
                "model": "mistral-embed",
                "configuration_revision": "mistral-embed-2023-12",
                "dimensions": 1024,
                "normalize": True,
                "batch_size": 32,
            },
        ),
    )
    for snapshot_id, capability, configuration in snapshots:
        serialized = json.dumps(configuration, sort_keys=True)
        op.execute(
            sa.text(
                "INSERT INTO configuration_snapshots "
                "(id, capability, schema_version, fingerprint, configuration_json) "
                "VALUES (CAST(:id AS uuid), :capability, 1, :fingerprint, "
                "CAST(:configuration AS jsonb))"
            ).bindparams(
                id=snapshot_id,
                capability=capability,
                fingerprint=_fingerprint(configuration),
                configuration=serialized,
            )
        )
    profiles = (
        (_NER_PROFILE_ID, "ner", "spacy-v1", _NER_SNAPSHOT_ID),
        (_CHUNKING_PROFILE_ID, "chunking", "page-window-v1", _CHUNKING_SNAPSHOT_ID),
        (_LEXICAL_PROFILE_ID, "lexical", "postgres-fts-simple-v1", _LEXICAL_SNAPSHOT_ID),
        (_EMBEDDING_PROFILE_ID, "embedding", "mistral-embed-v1", _EMBEDDING_SNAPSHOT_ID),
    )
    for profile_id, capability, name, snapshot_id in profiles:
        op.execute(
            sa.text(
                "INSERT INTO capability_profiles "
                "(id, capability, name, configuration_snapshot_id, status) "
                "VALUES (CAST(:id AS uuid), :capability, :name, "
                "CAST(:snapshot_id AS uuid), 'validated')"
            ).bindparams(
                id=profile_id,
                capability=capability,
                name=name,
                snapshot_id=snapshot_id,
            )
        )
    op.execute(
        sa.text(
            "INSERT INTO ingestion_profiles "
            "(id, ner_profile_id, chunking_profile_id, lexical_profile_id, embedding_profile_id) "
            "VALUES (CAST(:id AS uuid), CAST(:ner AS uuid), CAST(:chunking AS uuid), "
            "CAST(:lexical AS uuid), CAST(:embedding AS uuid))"
        ).bindparams(
            id=_INGESTION_PROFILE_ID,
            ner=_NER_PROFILE_ID,
            chunking=_CHUNKING_PROFILE_ID,
            lexical=_LEXICAL_PROFILE_ID,
            embedding=_EMBEDDING_PROFILE_ID,
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO active_profiles "
            "(id, scope, profile_kind, ingestion_profile_id, revision) "
            "VALUES (CAST(:id AS uuid), 'platform', 'ingestion', "
            "CAST(:profile_id AS uuid), 1)"
        ).bindparams(id=_ACTIVE_PROFILE_ID, profile_id=_INGESTION_PROFILE_ID)
    )
    op.execute(
        sa.text(
            "INSERT INTO profile_activations "
            "(id, scope, profile_kind, new_profile_id, reason, active_profile_revision) "
            "VALUES (CAST(:id AS uuid), 'platform', 'ingestion', "
            "CAST(:profile_id AS uuid), 'initial explicit baseline', 1)"
        ).bindparams(id=_ACTIVATION_ID, profile_id=_INGESTION_PROFILE_ID)
    )


def downgrade() -> None:
    """Remove profile/versioning structures without mutating existing derived rows."""
    op.drop_index(op.f("ix_chunk_embeddings_embedding_profile_id"), table_name="chunk_embeddings")
    op.drop_index(op.f("ix_chunk_embeddings_chunk_id"), table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_constraint("uq_chunks_index_generation_ordinal", "chunks", type_="unique")
    op.create_unique_constraint(
        op.f("uq_chunks_document_version_id"), "chunks", ["document_version_id", "ordinal"]
    )
    op.drop_index(op.f("ix_chunks_index_generation_id"), table_name="chunks")
    op.drop_constraint(
        "fk_chunks_index_generation_id_index_generations", "chunks", type_="foreignkey"
    )
    op.drop_column("chunks", "index_generation_id")
    op.drop_constraint(
        "fk_processing_jobs_index_generation_id_index_generations",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_processing_jobs_ingestion_profile_id_ingestion_profiles",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_column("processing_jobs", "index_generation_id")
    op.drop_column("processing_jobs", "ingestion_profile_id")
    op.drop_index(op.f("ix_index_generations_document_version_id"), table_name="index_generations")
    op.drop_index(op.f("ix_index_generations_tenant_id"), table_name="index_generations")
    op.drop_table("index_generations")
    op.drop_table("profile_activations")
    op.drop_table("active_profiles")
    op.drop_table("query_profile_embedding_cohorts")
    op.drop_table("query_profile_lexical_cohorts")
    op.drop_table("query_profiles")
    op.drop_table("ingestion_profiles")
    op.drop_table("capability_profiles")
    op.drop_table("configuration_snapshots")
