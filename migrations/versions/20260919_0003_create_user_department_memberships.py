"""Replace single user department with many-to-many memberships.

Revision ID: 20260919_0003
Revises: 20260919_0002
Create Date: 2026-09-19

Downgrading necessarily collapses multiple memberships to the first department UUID
because the previous schema can represent only one membership per user.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0003"
down_revision: str | None = "20260919_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create membership rows, backfill existing users, and remove the singular column."""
    op.create_unique_constraint(op.f("uq_users_id"), "users", ["id", "tenant_id"])
    op.create_table(
        "user_departments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id", "tenant_id"],
            ["departments.id", "departments.tenant_id"],
            name=op.f("fk_user_departments_department_id_departments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name=op.f("fk_user_departments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "department_id", name=op.f("pk_user_departments")),
    )
    op.create_index(
        op.f("ix_user_departments_tenant_id"),
        "user_departments",
        ["tenant_id"],
    )
    op.execute(
        """
        INSERT INTO user_departments (user_id, department_id, tenant_id)
        SELECT id, department_id, tenant_id
        FROM users
        """
    )
    op.drop_constraint(op.f("fk_users_department_id_departments"), "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_department_id"), table_name="users")
    op.drop_column("users", "department_id")


def downgrade() -> None:
    """Restore one deterministic department per user and remove membership rows."""
    op.add_column("users", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE users
        SET department_id = selected.department_id
        FROM (
            SELECT user_id, (array_agg(department_id ORDER BY department_id))[1] AS department_id
            FROM user_departments
            GROUP BY user_id
        ) AS selected
        WHERE users.id = selected.user_id
        """
    )
    op.alter_column("users", "department_id", nullable=False)
    op.create_index(op.f("ix_users_department_id"), "users", ["department_id"])
    op.create_foreign_key(
        op.f("fk_users_department_id_departments"),
        "users",
        "departments",
        ["department_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.drop_index(op.f("ix_user_departments_tenant_id"), table_name="user_departments")
    op.drop_table("user_departments")
    op.drop_constraint(op.f("uq_users_id"), "users", type_="unique")
