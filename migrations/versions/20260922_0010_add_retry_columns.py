"""Add retry tracking columns to processing_jobs.

- **Status:** In Review
- **Date:** 2026-09-22

Adds columns for retry behavior: last_attempt_at, next_retry_at, error_category,
failure_reason. Backfills existing rows with defaults.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0010"
down_revision = "20260921_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "processing_jobs",
        sa.Column(
            "error_category",
            sa.String(20),
            nullable=True,
            server_default="permanent",
        ),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("failure_reason", sa.String(100), nullable=True),
    )

    # Add check constraint for error_category values
    op.create_check_constraint(
        "valid_error_category",
        "processing_jobs",
        "error_category IN ('transient', 'permanent', 'timeout', 'configuration')",
    )


def downgrade() -> None:
    op.drop_constraint("valid_error_category", "processing_jobs", type_="check")
    op.drop_column("processing_jobs", "failure_reason")
    op.drop_column("processing_jobs", "error_category")
    op.drop_column("processing_jobs", "next_retry_at")
    op.drop_column("processing_jobs", "last_attempt_at")
