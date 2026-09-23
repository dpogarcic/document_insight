"""The migration provides a stable, isolated evaluation tenant."""

from uuid import UUID

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_migration_seeds_dedicated_evaluation_tenant_and_department() -> None:
    settings = _Settings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable test PostgreSQL is unavailable")
    owner_url = make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    engine = create_async_engine(owner_url)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT t.name, d.id, d.name FROM tenants t "
                        "JOIN departments d ON d.tenant_id = t.id "
                        "WHERE t.id = :tenant_id"
                    ),
                    {"tenant_id": UUID("cb08e54a-ba57-4b65-a128-20c33839e4d6")},
                )
            ).one()
        assert row == (
            "Document Insight Evaluation",
            UUID("cec53488-829d-4df2-b9bf-d80cb07027df"),
            "General",
        )
    finally:
        await engine.dispose()
