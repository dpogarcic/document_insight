"""Allow operator tenant selection from metadata and scope suite names per tenant.

Revision ID: 20260923_0018
Revises: 20260923_0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0018"
down_revision: str | None = "20260923_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expose tenant names only and keep revision numbering tenant local."""
    op.execute("GRANT SELECT (id, name) ON tenants TO di_profile_operator")
    op.execute(
        "CREATE POLICY tenant_operator_metadata ON tenants "
        "FOR SELECT TO di_profile_operator USING (true)"
    )
    op.drop_constraint("uq_evaluation_suite_revision", "evaluation_suite_revisions", type_="unique")
    op.create_unique_constraint(
        "uq_evaluation_suite_tenant_revision",
        "evaluation_suite_revisions",
        ["evaluation_tenant_id", "suite_name", "revision_number"],
    )


def downgrade() -> None:
    """Restore global numbering if no cross-tenant name/revision collisions exist.

    If suites with the same name and revision exist in different tenants, this
    downgrade must stop; restore the pre-migration backup to return to the old schema.
    """
    op.drop_constraint(
        "uq_evaluation_suite_tenant_revision", "evaluation_suite_revisions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_evaluation_suite_revision",
        "evaluation_suite_revisions",
        ["suite_name", "revision_number"],
    )
    op.execute("DROP POLICY tenant_operator_metadata ON tenants")
    op.execute("REVOKE SELECT (id, name) ON tenants FROM di_profile_operator")
