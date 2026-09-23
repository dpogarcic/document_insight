"""Grant the operator only document metadata needed for the evaluation picker.

Revision ID: 20260923_0019
Revises: 20260923_0018
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0019"
down_revision: str | None = "20260923_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expose tenant-scoped titles and current version IDs, never file content."""
    op.execute(
        "GRANT SELECT (id, tenant_id, title, current_ready_version_id) "
        "ON documents TO di_profile_operator"
    )
    op.execute(
        "CREATE POLICY document_operator_metadata ON documents "
        "FOR SELECT TO di_profile_operator USING (true)"
    )


def downgrade() -> None:
    """Remove the evaluation picker metadata grant and policy."""
    op.execute("DROP POLICY document_operator_metadata ON documents")
    op.execute(
        "REVOKE SELECT (id, tenant_id, title, current_ready_version_id) "
        "ON documents FROM di_profile_operator"
    )
