"""Create version-scoped chunks and PostgreSQL full-text index.

Revision ID: 20260921_0007
Revises: 20260921_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0007"
down_revision: str | None = "20260921_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create citation-ready chunks with a generated simple-language FTS vector."""
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint("end_offset > start_offset", name="offset_range"),
        sa.CheckConstraint("page_number >= 1", name="page_number_positive"),
    )
    op.create_index(op.f("ix_chunks_tenant_id"), "chunks", ["tenant_id"])
    op.create_index(op.f("ix_chunks_document_version_id"), "chunks", ["document_version_id"])
    op.create_index(
        "ix_chunks_tenant_document_version", "chunks", ["tenant_id", "document_version_id"]
    )
    op.create_index("ix_chunks_search_vector", "chunks", ["search_vector"], postgresql_using="gin")


def downgrade() -> None:
    """Remove chunks and chunking/index checkpoints."""
    op.drop_index("ix_chunks_search_vector", table_name="chunks")
    op.drop_index("ix_chunks_tenant_document_version", table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_version_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_tenant_id"), table_name="chunks")
    op.drop_table("chunks")
