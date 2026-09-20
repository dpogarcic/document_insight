"""Create canonical version-scoped NER metadata.

Revision ID: 20260921_0006
Revises: 20260920_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0006"
down_revision: str | None = "20260920_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add NER completion metadata and canonical document-version entities."""
    op.add_column("extracted_documents", sa.Column("detected_language", sa.String(8)))
    op.add_column("extracted_documents", sa.Column("ner_provider", sa.String(64)))
    op.add_column("extracted_documents", sa.Column("ner_model", sa.String(255)))
    op.add_column("extracted_documents", sa.Column("ner_completed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("display_value", sa.String(1024), nullable=False),
        sa.Column("normalized_value", sa.String(1024), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("ner_provider", sa.String(64), nullable=False),
        sa.Column("ner_model", sa.String(255), nullable=False),
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
        sa.UniqueConstraint("document_version_id", "label", "normalized_value"),
        sa.CheckConstraint("occurrence_count > 0", name="occurrence_count_positive"),
    )
    op.create_index(op.f("ix_entities_tenant_id"), "entities", ["tenant_id"])
    op.create_index(op.f("ix_entities_document_version_id"), "entities", ["document_version_id"])
    op.create_index(op.f("ix_entities_normalized_value"), "entities", ["normalized_value"])
    op.create_index(op.f("ix_entities_label"), "entities", ["label"])
    op.create_index(
        "ix_entities_tenant_label_normalized",
        "entities",
        ["tenant_id", "label", "normalized_value"],
    )


def downgrade() -> None:
    """Remove canonical entities and NER completion metadata."""
    op.drop_index("ix_entities_tenant_label_normalized", table_name="entities")
    op.drop_index(op.f("ix_entities_label"), table_name="entities")
    op.drop_index(op.f("ix_entities_normalized_value"), table_name="entities")
    op.drop_index(op.f("ix_entities_document_version_id"), table_name="entities")
    op.drop_index(op.f("ix_entities_tenant_id"), table_name="entities")
    op.drop_table("entities")
    op.drop_column("extracted_documents", "ner_completed_at")
    op.drop_column("extracted_documents", "ner_model")
    op.drop_column("extracted_documents", "ner_provider")
    op.drop_column("extracted_documents", "detected_language")
