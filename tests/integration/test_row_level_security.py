"""PostgreSQL checks for the database tenant-isolation boundary.

Set TEST_DATABASE_RUNTIME_URL to a migrated, disposable PostgreSQL database using
the same restricted role as the API. SQLite cannot exercise PostgreSQL RLS.
"""

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class _DatabaseTestSettings(BaseSettings):
    """Load the optional runtime URL from the same `.env` file used by Compose."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous database checks on asyncio."""
    return "asyncio"


@pytest.mark.anyio
async def test_runtime_role_cannot_bypass_forced_rls_on_tenant_data() -> None:
    """Every tenant-owned table must enforce RLS for the API's database role."""
    database_url = _DatabaseTestSettings().test_database_runtime_url
    if not database_url:
        pytest.skip("TEST_DATABASE_RUNTIME_URL is required for PostgreSQL RLS checks")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_RUNTIME_URL must use PostgreSQL with asyncpg")

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            role = (
                await connection.execute(
                    text(
                        "SELECT current_user, current_database(), rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
            rows = (
                await connection.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                        "pg_get_userbyid(c.relowner) = current_user AS runtime_owns_table, "
                        "has_table_privilege(current_user, c.oid, 'SELECT') AS can_select "
                        "FROM pg_class AS c "
                        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    protected_tables = {
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
    }
    table_state = {
        name: (enabled, forced, owned, can_select)
        for name, enabled, forced, owned, can_select in rows
        if name in protected_tables
    }
    assert set(table_state) == protected_tables
    assert role == ("document_insight_test_runtime", "document_insight_test", False, False)
    unprotected = {
        name: state for name, state in table_state.items() if state != (True, True, False, True)
    }
    assert unprotected == {}
