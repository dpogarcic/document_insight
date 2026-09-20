"""Create durable processing jobs before queue publication.

Revision ID: 20260920_0004
Revises: 20260919_0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0004"
down_revision: str | None = "20260919_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one durable, idempotent processing job per document version."""
    op.create_unique_constraint(
        op.f("uq_document_versions_id"),
        "document_versions",
        ["id", "tenant_id"],
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_processing_jobs_non_negative_attempt_count"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed', 'cancelled')",
            name=op.f("ck_processing_jobs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_processing_jobs_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            name=op.f("fk_processing_jobs_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_processing_jobs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_processing_jobs_idempotency_key")),
    )
    op.create_index(
        op.f("ix_processing_jobs_correlation_id"),
        "processing_jobs",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_processing_jobs_document_version_id"),
        "processing_jobs",
        ["document_version_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_processing_jobs_status"),
        "processing_jobs",
        ["status"],
    )
    op.create_index(
        op.f("ix_processing_jobs_tenant_id"),
        "processing_jobs",
        ["tenant_id"],
    )


def downgrade() -> None:
    """Remove processing jobs and their composite document-version key."""
    op.drop_index(op.f("ix_processing_jobs_tenant_id"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_status"), table_name="processing_jobs")
    op.drop_index(
        op.f("ix_processing_jobs_document_version_id"),
        table_name="processing_jobs",
    )
    op.drop_index(op.f("ix_processing_jobs_correlation_id"), table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_constraint(
        op.f("uq_document_versions_id"),
        "document_versions",
        type_="unique",
    )
