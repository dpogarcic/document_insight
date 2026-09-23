"""Provision the dedicated evaluation tenant and its initial department.

Revision ID: 20260923_0016
Revises: 20260923_0015

The tenant and department IDs are stable so EVALUATION_TENANT_ID can refer to the
same isolated corpus after a local database rebuild. Credentials are provisioned
separately and are never embedded in a migration.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0016"
down_revision: str | None = "20260923_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVALUATION_TENANT_ID = UUID("cb08e54a-ba57-4b65-a128-20c33839e4d6")
EVALUATION_DEPARTMENT_ID = UUID("cec53488-829d-4df2-b9bf-d80cb07027df")


def upgrade() -> None:
    """Create the isolated evaluation tenant without granting anyone access."""
    connection = op.get_bind()
    connection.execute(
        sa.text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
        {"id": EVALUATION_TENANT_ID, "name": "Document Insight Evaluation"},
    )
    connection.execute(
        sa.text("INSERT INTO departments (id, tenant_id, name) VALUES (:id, :tenant_id, :name)"),
        {
            "id": EVALUATION_DEPARTMENT_ID,
            "tenant_id": EVALUATION_TENANT_ID,
            "name": "General",
        },
    )


def downgrade() -> None:
    """Remove only an unused seed; refuse to cascade evaluation data."""
    connection = op.get_bind()
    for statement, parameters in (
        (
            "SELECT 1 FROM users WHERE tenant_id = :tenant_id LIMIT 1",
            {"tenant_id": EVALUATION_TENANT_ID},
        ),
        (
            "SELECT 1 FROM documents WHERE tenant_id = :tenant_id LIMIT 1",
            {"tenant_id": EVALUATION_TENANT_ID},
        ),
        (
            "SELECT 1 FROM evaluation_suite_revisions WHERE evaluation_tenant_id = :tenant_id LIMIT 1",
            {"tenant_id": EVALUATION_TENANT_ID},
        ),
        (
            "SELECT 1 FROM active_profiles WHERE scope = :scope LIMIT 1",
            {"scope": f"evaluation:{EVALUATION_TENANT_ID}"},
        ),
        (
            "SELECT 1 FROM departments WHERE tenant_id = :tenant_id AND id != :department_id LIMIT 1",
            {"tenant_id": EVALUATION_TENANT_ID, "department_id": EVALUATION_DEPARTMENT_ID},
        ),
    ):
        if connection.execute(sa.text(statement), parameters).first() is not None:
            raise RuntimeError("Evaluation tenant contains data; remove it before downgrade")
    connection.execute(
        sa.text("DELETE FROM departments WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": EVALUATION_DEPARTMENT_ID, "tenant_id": EVALUATION_TENANT_ID},
    )
    connection.execute(
        sa.text("DELETE FROM tenants WHERE id = :id"),
        {"id": EVALUATION_TENANT_ID},
    )
