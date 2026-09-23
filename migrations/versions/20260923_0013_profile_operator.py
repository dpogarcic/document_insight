"""Grant a dedicated platform operator only configuration control-plane access.

Revision ID: 20260923_0013
Revises: 20260923_0012
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0013"
down_revision: str | None = "20260923_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Provision a non-login operator role and a separately bootstrapped login."""
    op.execute("CREATE ROLE di_profile_operator NOLOGIN")
    op.execute("CREATE ROLE di_profile_operator_login NOLOGIN")
    op.execute("GRANT di_profile_operator TO di_profile_operator_login")
    op.execute("GRANT USAGE ON SCHEMA public TO di_profile_operator")
    op.execute(
        "GRANT SELECT, INSERT ON configuration_snapshots, capability_profiles, "
        "ingestion_profiles, query_profiles, query_profile_lexical_cohorts, "
        "query_profile_embedding_cohorts, profile_activations TO di_profile_operator"
    )
    op.execute("GRANT UPDATE (status) ON capability_profiles TO di_profile_operator")
    op.execute("GRANT SELECT, UPDATE ON active_profiles TO di_profile_operator")
    op.execute("GRANT SELECT ON index_generations TO di_profile_operator")
    op.execute(
        "CREATE POLICY profile_operator_select ON index_generations "
        "FOR SELECT TO di_profile_operator USING (true)"
    )


def downgrade() -> None:
    """Remove the dedicated operator credential and its grants."""
    op.execute("DROP POLICY profile_operator_select ON index_generations")
    op.execute("DROP OWNED BY di_profile_operator_login")
    op.execute("DROP ROLE di_profile_operator_login")
    op.execute("DROP OWNED BY di_profile_operator")
    op.execute("DROP ROLE di_profile_operator")
