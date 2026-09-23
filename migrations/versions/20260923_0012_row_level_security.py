"""Enforce current tenant and department authorization in PostgreSQL.

Revision ID: 20260923_0012
Revises: 20260922_0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0012"
down_revision: str | None = "20260922_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = (
    "di_api_read",
    "di_api_write",
    "di_auth",
    "di_worker",
    "di_reconciler",
    "di_monitor",
)
_LOGIN_ROLES = {
    "di_api_read_login": "di_api_read",
    "di_api_write_login": "di_api_write",
    "di_auth_login": "di_auth",
    "di_worker_login": "di_worker",
    "di_reconciler_login": "di_reconciler",
    "di_monitor_login": "di_monitor",
}
_PROTECTED = (
    "tenants",
    "departments",
    "users",
    "user_departments",
    "documents",
    "document_departments",
    "document_versions",
    "processing_jobs",
    "extracted_documents",
    "entities",
    "index_generations",
    "chunks",
    "chunk_embeddings",
)


def _policy(
    table: str,
    name: str,
    action: str,
    role: str,
    using: str | None = None,
    check: str | None = None,
) -> None:
    """Create one named policy without interpolating untrusted values."""
    statement = f"CREATE POLICY {name} ON {table} FOR {action} TO {role}"
    if using is not None:
        statement += f" USING ({using})"
    if check is not None:
        statement += f" WITH CHECK ({check})"
    op.execute(statement)


def upgrade() -> None:
    """Create role capabilities, safe authorization helpers, and fail-closed policies."""
    for role in _ROLES:
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
        "'di_policy_owner') THEN CREATE ROLE di_policy_owner NOLOGIN BYPASSRLS; "
        "END IF; END $$"
    )
    for login, capability in _LOGIN_ROLES.items():
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login}') "
            f"THEN CREATE ROLE {login} NOLOGIN; END IF; END $$"
        )
        op.execute(f"GRANT {capability} TO {login}")
    op.execute("GRANT di_api_read TO di_api_write")
    # The disposable integration role exists before Alembic runs.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = 'document_insight_test_runtime') THEN "
        "GRANT di_api_write TO document_insight_test_runtime; END IF; END $$"
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS rls")
    op.execute("REVOKE ALL ON SCHEMA rls FROM PUBLIC")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    op.execute("""
        CREATE FUNCTION rls.actor_id() RETURNS uuid LANGUAGE sql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$
    """)
    op.execute("""
        CREATE FUNCTION rls.job_id() RETURNS uuid LANGUAGE sql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT NULLIF(current_setting('app.job_id', true), '')::uuid $$
    """)
    op.execute("""
        CREATE FUNCTION rls.actor_tenant_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT u.tenant_id FROM public.users AS u WHERE u.id = rls.actor_id() $$
    """)
    op.execute("""
        CREATE FUNCTION rls.actor_is_admin() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (SELECT 1 FROM public.users AS u
             WHERE u.id = rls.actor_id() AND u.role = 'tenant_admin') $$
    """)
    op.execute("""
        CREATE FUNCTION rls.can_read_document(p_document_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.documents AS d
            JOIN public.users AS u ON u.id = rls.actor_id() AND u.tenant_id = d.tenant_id
            WHERE d.id = p_document_id AND (
                u.role = 'tenant_admin' OR EXISTS (
                    SELECT 1 FROM public.document_departments AS dd
                    JOIN public.user_departments AS ud
                      ON ud.department_id = dd.department_id
                     AND ud.tenant_id = dd.tenant_id
                    WHERE dd.document_id = d.id AND ud.user_id = u.id
                )
            )
        ) $$
    """)
    op.execute("""
        CREATE FUNCTION rls.can_read_version(p_version_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.document_versions AS v
            WHERE v.id = p_version_id AND rls.can_read_document(v.document_id)
        ) $$
    """)
    op.execute("""
        CREATE FUNCTION rls.can_read_chunk(p_chunk_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.chunks AS c
            WHERE c.id = p_chunk_id AND rls.can_read_version(c.document_version_id)
        ) $$
    """)
    op.execute("""
        CREATE FUNCTION rls.worker_can_access_version(p_version_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.processing_jobs AS j
            WHERE j.id = rls.job_id() AND j.document_version_id = p_version_id
        ) $$
    """)
    op.execute("""
        CREATE FUNCTION rls.worker_can_access_chunk(p_chunk_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.chunks AS c
            WHERE c.id = p_chunk_id AND rls.worker_can_access_version(c.document_version_id)
        ) $$
    """)
    op.execute("""
        CREATE FUNCTION rls.can_assign_department(p_document_id uuid, p_department_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT EXISTS (
            SELECT 1 FROM public.documents AS d
            JOIN public.departments AS dep
              ON dep.id = p_department_id AND dep.tenant_id = d.tenant_id
            JOIN public.users AS u
              ON u.id = rls.actor_id() AND u.tenant_id = d.tenant_id
            WHERE d.id = p_document_id AND (
                u.role = 'tenant_admin' OR (
                    u.role = 'editor' AND d.created_by = u.id
                    AND d.xmin::text = txid_current()::text AND EXISTS (
                        SELECT 1 FROM public.user_departments AS ud
                        WHERE ud.user_id = u.id AND ud.tenant_id = d.tenant_id
                          AND ud.department_id = p_department_id
                    )
                )
            )
        ) $$
    """)
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rls FROM PUBLIC")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rls TO di_policy_owner")
    op.execute("GRANT USAGE ON SCHEMA public, rls TO " + ", ".join((*_ROLES, "di_policy_owner")))
    op.execute(
        "GRANT SELECT ON users, user_departments, departments, documents, "
        "document_departments, document_versions, processing_jobs, chunks "
        "TO di_policy_owner"
    )
    for function in (
        "actor_tenant_id()",
        "actor_is_admin()",
        "can_read_document(uuid)",
        "can_read_version(uuid)",
        "can_read_chunk(uuid)",
        "worker_can_access_version(uuid)",
        "worker_can_access_chunk(uuid)",
        "can_assign_department(uuid, uuid)",
    ):
        op.execute(f"ALTER FUNCTION rls.{function} OWNER TO di_policy_owner")
    op.execute(
        "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rls TO "
        "di_api_read, di_api_write, di_worker, di_reconciler"
    )

    for table in _PROTECTED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Identity is read from PostgreSQL on every authenticated request. Registration
    # and login use a separate role with no document or passage grants.
    _policy("tenants", "tenant_self_read", "SELECT", "di_api_read", "id = rls.actor_tenant_id()")
    _policy("tenants", "tenant_auth_all", "ALL", "di_auth", "true", "true")
    _policy(
        "departments",
        "department_member_read",
        "SELECT",
        "di_api_read",
        "tenant_id = rls.actor_tenant_id() AND (rls.actor_is_admin() OR "
        "EXISTS (SELECT 1 FROM public.user_departments ud "
        "WHERE ud.user_id = rls.actor_id() AND ud.department_id = id))",
    )
    _policy("departments", "department_auth_all", "ALL", "di_auth", "true", "true")
    _policy("users", "user_self_read", "SELECT", "di_api_read", "id = rls.actor_id()")
    _policy("users", "user_auth_all", "ALL", "di_auth", "true", "true")
    _policy(
        "user_departments",
        "membership_self_read",
        "SELECT",
        "di_api_read",
        "user_id = rls.actor_id() AND tenant_id = rls.actor_tenant_id()",
    )
    _policy("user_departments", "membership_auth_all", "ALL", "di_auth", "true", "true")

    _policy(
        "documents",
        "document_authorized_read",
        "SELECT",
        "di_api_read",
        "rls.can_read_document(id)",
    )
    _policy(
        "documents",
        "document_authorized_insert",
        "INSERT",
        "di_api_write",
        check="tenant_id = rls.actor_tenant_id() AND created_by = rls.actor_id() "
        "AND EXISTS (SELECT 1 FROM public.users u WHERE u.id = rls.actor_id() "
        "AND u.role IN ('tenant_admin', 'editor'))",
    )
    _policy(
        "documents",
        "document_admin_update",
        "UPDATE",
        "di_api_write",
        "tenant_id = rls.actor_tenant_id() AND rls.actor_is_admin()",
        "tenant_id = rls.actor_tenant_id() AND rls.actor_is_admin()",
    )

    _policy(
        "document_departments",
        "assignment_authorized_read",
        "SELECT",
        "di_api_read",
        "rls.can_read_document(document_id)",
    )
    _policy(
        "document_departments",
        "assignment_initial_insert",
        "INSERT",
        "di_api_write",
        check="tenant_id = rls.actor_tenant_id() "
        "AND rls.can_assign_department(document_id, department_id)",
    )
    _policy(
        "document_departments",
        "assignment_admin_delete",
        "DELETE",
        "di_api_write",
        "tenant_id = rls.actor_tenant_id() AND rls.actor_is_admin()",
    )

    _policy(
        "document_versions",
        "version_authorized_read",
        "SELECT",
        "di_api_read",
        "rls.can_read_version(id)",
    )
    _policy(
        "document_versions",
        "version_authorized_insert",
        "INSERT",
        "di_api_write",
        check="tenant_id = rls.actor_tenant_id() AND created_by = rls.actor_id() "
        "AND rls.can_read_document(document_id)",
    )
    _policy(
        "document_versions",
        "version_worker_update",
        "UPDATE",
        "di_worker",
        "rls.worker_can_access_version(id)",
        "rls.worker_can_access_version(id)",
    )
    _policy(
        "document_versions",
        "version_worker_read",
        "SELECT",
        "di_worker",
        "rls.worker_can_access_version(id)",
    )
    _policy("document_versions", "version_reconciler_read", "SELECT", "di_reconciler", "true")
    _policy(
        "document_versions", "version_reconciler_update", "UPDATE", "di_reconciler", "true", "true"
    )

    _policy(
        "processing_jobs",
        "job_authorized_read",
        "SELECT",
        "di_api_read",
        "rls.can_read_version(document_version_id)",
    )
    _policy(
        "processing_jobs",
        "job_authorized_insert",
        "INSERT",
        "di_api_write",
        check="tenant_id = rls.actor_tenant_id() AND created_by = rls.actor_id() "
        "AND rls.can_read_version(document_version_id)",
    )
    _policy(
        "processing_jobs",
        "job_creator_update",
        "UPDATE",
        "di_api_write",
        "created_by = rls.actor_id() AND rls.can_read_version(document_version_id)",
        "created_by = rls.actor_id() AND rls.can_read_version(document_version_id)",
    )
    _policy("processing_jobs", "job_worker_read", "SELECT", "di_worker", "id = rls.job_id()")
    _policy(
        "processing_jobs",
        "job_worker_update",
        "UPDATE",
        "di_worker",
        "id = rls.job_id()",
        "id = rls.job_id()",
    )
    _policy("processing_jobs", "job_reconciler_read", "SELECT", "di_reconciler", "true")
    _policy("processing_jobs", "job_reconciler_update", "UPDATE", "di_reconciler", "true", "true")
    _policy("processing_jobs", "job_monitor_read", "SELECT", "di_monitor", "true")

    for table in ("extracted_documents", "entities", "index_generations", "chunks"):
        _policy(
            table,
            f"{table}_authorized_read",
            "SELECT",
            "di_api_read",
            "rls.can_read_version(document_version_id)",
        )
        _policy(
            table,
            f"{table}_worker_read",
            "SELECT",
            "di_worker",
            "rls.worker_can_access_version(document_version_id)",
        )
        _policy(
            table,
            f"{table}_worker_insert",
            "INSERT",
            "di_worker",
            check="rls.worker_can_access_version(document_version_id)",
        )
        _policy(
            table,
            f"{table}_worker_update",
            "UPDATE",
            "di_worker",
            "rls.worker_can_access_version(document_version_id)",
            "rls.worker_can_access_version(document_version_id)",
        )
    _policy(
        "index_generations",
        "generation_api_insert",
        "INSERT",
        "di_api_write",
        check="tenant_id = rls.actor_tenant_id() AND rls.can_read_version(document_version_id)",
    )
    _policy(
        "chunk_embeddings",
        "embedding_authorized_read",
        "SELECT",
        "di_api_read",
        "rls.can_read_chunk(chunk_id)",
    )
    _policy(
        "chunk_embeddings",
        "embedding_worker_read",
        "SELECT",
        "di_worker",
        "rls.worker_can_access_chunk(chunk_id)",
    )
    _policy(
        "chunk_embeddings",
        "embedding_worker_insert",
        "INSERT",
        "di_worker",
        check="rls.worker_can_access_chunk(chunk_id)",
    )

    op.execute(
        "GRANT SELECT ON tenants, departments, users, user_departments, documents, "
        "document_departments, document_versions, processing_jobs, extracted_documents, "
        "entities, index_generations, chunks, chunk_embeddings TO di_api_read"
    )
    op.execute("GRANT SELECT, INSERT ON tenants, departments, users, user_departments TO di_auth")
    op.execute("GRANT INSERT, UPDATE ON documents TO di_api_write")
    op.execute("GRANT INSERT, DELETE ON document_departments TO di_api_write")
    op.execute("GRANT INSERT ON document_versions, index_generations TO di_api_write")
    op.execute("GRANT INSERT, UPDATE ON processing_jobs TO di_api_write")
    op.execute("GRANT SELECT, UPDATE ON document_versions, processing_jobs TO di_worker")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON extracted_documents, entities, "
        "index_generations, chunks, chunk_embeddings TO di_worker"
    )
    op.execute("GRANT SELECT, UPDATE ON document_versions, processing_jobs TO di_reconciler")
    op.execute("GRANT SELECT ON processing_jobs TO di_monitor")
    op.execute(
        "GRANT SELECT ON configuration_snapshots, capability_profiles, "
        "ingestion_profiles, query_profiles, query_profile_lexical_cohorts, "
        "query_profile_embedding_cohorts, active_profiles TO "
        "di_api_read, di_api_write, di_worker, di_reconciler"
    )


def downgrade() -> None:
    """Remove RLS policies and helpers; retain role objects for controlled deprovisioning."""
    for table in reversed(_PROTECTED):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP SCHEMA rls CASCADE")
