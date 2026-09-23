"""The private profile operator can change policy pointers without passage access."""

from uuid import uuid4

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from document_insight.application.configuration.approval import ProfileApprovalService
from document_insight.application.configuration.catalog import ProfileCatalogService
from document_insight.application.configuration.models import Capability
from document_insight.application.query.profile_resolver import QueryProfileResolver
from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.ingestion_profile.repository import (
    SqlAlchemyIngestionProfileRepository,
)
from document_insight.infrastructure.profile_activation.repository import (
    SqlAlchemyProfileActivationRepository,
)
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)


class _TestSettings(BaseSettings):
    """Load only disposable test-database credentials from the ignored local env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio for PostgreSQL integration checks."""
    return "asyncio"


def _owner_url():  # type: ignore[no-untyped-def]
    """Derive the disposable test owner URL without printing credentials."""
    settings = _TestSettings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable PostgreSQL test credentials are required")
    return make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )


@pytest.mark.anyio
async def test_operator_role_has_configuration_grants_without_document_access() -> None:
    """Profile approval does not reuse a tenant API or migration-owner credential."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET ROLE di_profile_operator"))
            grants = await connection.execute(
                text("""
                SELECT
                    has_table_privilege(current_user, 'configuration_snapshots', 'INSERT'),
                    has_table_privilege(current_user, 'capability_profiles', 'INSERT'),
                    has_table_privilege(current_user, 'active_profiles', 'UPDATE'),
                    has_table_privilege(current_user, 'profile_activations', 'INSERT'),
                    has_table_privilege(current_user, 'chunks', 'SELECT'),
                    has_table_privilege(current_user, 'documents', 'SELECT')
            """)
            )
            assert grants.one() == (True, True, True, True, False, False)
            await connection.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_operator_activates_new_ingestion_while_retaining_old_embedding_cohort() -> None:
    """Run the approval flow through restricted PostgreSQL grants and real repositories."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET LOCAL ROLE di_profile_operator"))
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    snapshots = SqlAlchemyConfigurationSnapshotRepository(session)
                    capabilities = SqlAlchemyCapabilityProfileRepository(session)
                    ingestions = SqlAlchemyIngestionProfileRepository(session)
                    queries = SqlAlchemyQueryProfileRepository(session)
                    active = SqlAlchemyActiveProfileRepository(session)
                    service = ProfileApprovalService(
                        snapshots,
                        capabilities,
                        ingestions,
                        queries,
                        active,
                        SqlAlchemyIndexGenerationRepository(session),
                        SqlAlchemyProfileActivationRepository(session),
                        SqlAlchemyTransactionManager(session),
                        True,
                    )
                    old_ingestion = await active.lock("platform", "ingestion")
                    old_query = await active.lock("platform", "query")
                    assert old_ingestion is not None and old_query is not None
                    ingestion = await ingestions.get(old_ingestion.profile_id)
                    query = await queries.get(old_query.profile_id)
                    assert ingestion is not None and query is not None
                    retrieval = await snapshots.get(query.retrieval_snapshot_id)
                    assert retrieval is not None
                    await session.commit()

                    new_embedding = await service.create_capability(
                        Capability.EMBEDDING,
                        f"test-embedding-{uuid4()}",
                        {
                            "provider": "mistral",
                            "model": "mistral-embed-v2",
                            "configuration_revision": "v2",
                            "dimensions": 1024,
                            "normalize": True,
                            "batch_size": 16,
                        },
                    )
                    await service.validate_capability(new_embedding)
                    new_query = await service.create_query(
                        query.lexical_profile_ids,
                        (*query.embedding_profile_ids, new_embedding),
                        query.reranker_profile_id,
                        query.generation_profile_id,
                        retrieval.configuration,
                    )
                    actor = uuid4()
                    await service.activate(
                        "query", new_query, old_query.revision, actor, "read both cohorts"
                    )
                    new_ingestion = await service.create_ingestion(
                        ingestion.ner_profile_id,
                        ingestion.chunking_profile_id,
                        ingestion.lexical_profile_id,
                        new_embedding,
                    )
                    await service.activate(
                        "ingestion",
                        new_ingestion,
                        old_ingestion.revision,
                        actor,
                        "new uploads use v2",
                    )
                    resolved = await QueryProfileResolver(queries, capabilities, snapshots).resolve(
                        new_query
                    )
                    assert ingestion.embedding_profile_id in resolved.embedding_profile_ids
                    assert new_embedding in resolved.embedding_profile_ids
                    assert {
                        configuration.model
                        for _, configuration in resolved.embedding_configurations
                    } == {
                        "mistral-embed",
                        "mistral-embed-v2",
                    }
                    catalog = ProfileCatalogService(
                        capabilities, ingestions, queries, snapshots, active
                    )
                    overview = await catalog.list_all()
                    assert overview.active_query is not None
                    assert overview.active_query.profile_id == new_query
                    assert any(item.profile_id == new_embedding for item in overview.capabilities)
                    assert (await catalog.capability(new_embedding)) is not None
                    assert (await catalog.query(new_query)) is not None
                # Roll back the outer transaction so this integration test leaves no active-policy change.
                await connection.rollback()
    finally:
        await engine.dispose()
