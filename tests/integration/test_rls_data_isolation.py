"""Exercise tenant and department RLS against real PostgreSQL rows."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Uuid, bindparam, delete, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from document_insight.infrastructure.capability_profile.model import CapabilityProfileModel
from document_insight.infrastructure.chunk.model import ChunkModel
from document_insight.infrastructure.chunk_embedding.model import ChunkEmbeddingModel
from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_version.model import DocumentVersionModel
from document_insight.infrastructure.entity.model import EntityModel
from document_insight.infrastructure.extracted_document.model import ExtractedDocumentModel
from document_insight.infrastructure.index_generation.model import IndexGenerationModel
from document_insight.infrastructure.ingestion_profile.model import IngestionProfileModel
from document_insight.infrastructure.job.model import JobModel
from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user_department.model import UserDepartmentModel


class _DatabaseTestSettings(BaseSettings):
    """Read test-only credentials from the local environment or ignored `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None
    database_read_password: str | None = None
    database_write_password: str | None = None
    database_auth_password: str | None = None
    database_worker_password: str | None = None


@dataclass(frozen=True)
class _Actor:
    """Identity used to establish one transaction's expected SQL scope."""

    tenant_id: UUID
    user_id: UUID
    role: str


@dataclass(frozen=True)
class _DocumentRows:
    """Identifiers for one document and each derived, protected row."""

    document_id: UUID
    version_id: UUID
    job_id: UUID
    generation_id: UUID
    chunk_id: UUID
    embedding_id: UUID
    entity_id: UUID


@dataclass(frozen=True)
class _IsolationFixture:
    """Three documents spanning two tenants and two departments."""

    runtime_engine: AsyncEngine
    owner_engine: AsyncEngine
    tenant_a_viewer: _Actor
    tenant_a_admin: _Actor
    tenant_b_admin: _Actor
    tenant_a_department_id: UUID
    tenant_b_department_id: UUID
    tenant_a_department_document: _DocumentRows
    tenant_a_other_department_document: _DocumentRows
    tenant_b_document: _DocumentRows


@pytest.fixture
def anyio_backend() -> str:
    """Run async PostgreSQL checks on asyncio."""
    return "asyncio"


def _test_urls() -> tuple[URL, URL]:
    """Require the dedicated database and derive its owner URL without exposing a secret."""
    settings = _DatabaseTestSettings()
    if not settings.test_database_runtime_url:
        pytest.skip("TEST_DATABASE_RUNTIME_URL is required for PostgreSQL RLS checks")
    if not settings.test_database_owner_password:
        pytest.skip("TEST_DATABASE_OWNER_PASSWORD is required for PostgreSQL RLS fixtures")
    runtime_url = make_url(settings.test_database_runtime_url)
    if (
        runtime_url.drivername != "postgresql+asyncpg"
        or runtime_url.username != "document_insight_test_runtime"
        or runtime_url.database != "document_insight_test"
    ):
        pytest.fail("RLS integration tests require the disposable PostgreSQL runtime role")
    owner_url = runtime_url.set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    return owner_url, runtime_url


async def _seed_document(
    owner_engine: AsyncEngine,
    tenant_id: UUID,
    department_id: UUID,
    creator_id: UUID,
    ingestion_profile_id: UUID,
    embedding_profile_id: UUID,
) -> _DocumentRows:
    """Commit one ready document with a job, entity, passage, and vector."""
    rows = _DocumentRows(*(uuid4() for _ in range(7)))
    async with owner_engine.begin() as connection:
        document = DocumentModel(
            id=rows.document_id,
            tenant_id=tenant_id,
            title=f"RLS fixture {rows.document_id}",
            created_by=creator_id,
        )
        version = DocumentVersionModel(
            id=rows.version_id,
            document_id=rows.document_id,
            tenant_id=tenant_id,
            version_number=1,
            original_filename="fixture.pdf",
            object_key=f"rls-fixtures/{rows.version_id}",
            media_type="application/pdf",
            size_bytes=8,
            content_sha256=b"0" * 32,
            status="ready",
            created_by=creator_id,
        )
        await connection.execute(
            DocumentModel.__table__.insert().values(
                id=document.id,
                tenant_id=document.tenant_id,
                title=document.title,
                created_by=document.created_by,
            )
        )
        await connection.execute(
            DocumentDepartmentModel.__table__.insert().values(
                document_id=rows.document_id,
                department_id=department_id,
                tenant_id=tenant_id,
            )
        )
        await connection.execute(
            DocumentVersionModel.__table__.insert().values(
                id=version.id,
                document_id=version.document_id,
                tenant_id=version.tenant_id,
                version_number=version.version_number,
                original_filename=version.original_filename,
                object_key=version.object_key,
                media_type=version.media_type,
                size_bytes=version.size_bytes,
                content_sha256=version.content_sha256,
                status=version.status,
                created_by=version.created_by,
            )
        )
        await connection.execute(
            update(DocumentModel)
            .where(DocumentModel.id == rows.document_id)
            .values(current_ready_version_id=rows.version_id)
        )
        await connection.execute(
            JobModel.__table__.insert().values(
                id=rows.job_id,
                tenant_id=tenant_id,
                document_version_id=rows.version_id,
                ingestion_profile_id=ingestion_profile_id,
                index_generation_id=None,
                idempotency_key=uuid4(),
                correlation_id=uuid4(),
                status="ready",
                attempt_count=0,
                created_by=creator_id,
            )
        )
        await connection.execute(
            ExtractedDocumentModel.__table__.insert().values(
                document_version_id=rows.version_id,
                tenant_id=tenant_id,
                text="shared rls fixture passage",
                page_count=1,
                parser_name="test",
                parser_version="1",
            )
        )
        await connection.execute(
            EntityModel.__table__.insert().values(
                id=rows.entity_id,
                tenant_id=tenant_id,
                document_version_id=rows.version_id,
                display_value="RLS Fixture",
                normalized_value="rls fixture",
                label="ORG",
                occurrence_count=1,
                language="en",
                ner_provider="test",
                ner_model="test",
            )
        )
        await connection.execute(
            IndexGenerationModel.__table__.insert().values(
                id=rows.generation_id,
                tenant_id=tenant_id,
                document_version_id=rows.version_id,
                ingestion_profile_id=ingestion_profile_id,
                status="ready",
            )
        )
        await connection.execute(
            ChunkModel.__table__.insert().values(
                id=rows.chunk_id,
                tenant_id=tenant_id,
                document_version_id=rows.version_id,
                index_generation_id=rows.generation_id,
                ordinal=0,
                text="shared rls fixture passage",
                start_offset=0,
                end_offset=26,
                page_number=1,
                language="en",
            )
        )
        await connection.execute(
            ChunkEmbeddingModel.__table__.insert().values(
                id=rows.embedding_id,
                chunk_id=rows.chunk_id,
                embedding_profile_id=embedding_profile_id,
                embedding=[0.1, 0.2, 0.3],
            )
        )
    return rows


@pytest.fixture
async def isolation_rows() -> AsyncIterator[_IsolationFixture]:
    """Seed the dedicated test database through its owner, then clean up all rows."""
    owner_url, runtime_url = _test_urls()
    owner_engine = create_async_engine(owner_url)
    runtime_engine = create_async_engine(runtime_url)
    tenant_a, tenant_b = uuid4(), uuid4()
    a_department, a_other_department, b_department = uuid4(), uuid4(), uuid4()
    a_admin, a_viewer, b_admin = uuid4(), uuid4(), uuid4()
    document_ids: list[UUID] = []
    try:
        async with owner_engine.begin() as connection:
            profile_id = await connection.scalar(select(IngestionProfileModel.id).limit(1))
            embedding_profile_id = await connection.scalar(
                select(CapabilityProfileModel.id)
                .where(CapabilityProfileModel.capability == "embedding")
                .limit(1)
            )
            assert profile_id is not None
            assert embedding_profile_id is not None
            await connection.execute(
                TenantModel.__table__.insert(),
                [
                    {"id": tenant_a, "name": f"RLS A {tenant_a}"},
                    {"id": tenant_b, "name": f"RLS B {tenant_b}"},
                ],
            )
            await connection.execute(
                DepartmentModel.__table__.insert(),
                [
                    {"id": a_department, "tenant_id": tenant_a, "name": "A permitted"},
                    {"id": a_other_department, "tenant_id": tenant_a, "name": "A denied"},
                    {"id": b_department, "tenant_id": tenant_b, "name": "B permitted"},
                ],
            )
            await connection.execute(
                UserModel.__table__.insert(),
                [
                    {
                        "id": a_admin,
                        "tenant_id": tenant_a,
                        "email": f"a-{a_admin}@example.test",
                        "display_name": "A admin",
                        "password_hash": "test",
                        "role": "tenant_admin",
                    },
                    {
                        "id": a_viewer,
                        "tenant_id": tenant_a,
                        "email": f"v-{a_viewer}@example.test",
                        "display_name": "A viewer",
                        "password_hash": "test",
                        "role": "viewer",
                    },
                    {
                        "id": b_admin,
                        "tenant_id": tenant_b,
                        "email": f"b-{b_admin}@example.test",
                        "display_name": "B admin",
                        "password_hash": "test",
                        "role": "tenant_admin",
                    },
                ],
            )
            await connection.execute(
                UserDepartmentModel.__table__.insert(),
                [
                    {"user_id": a_admin, "department_id": a_department, "tenant_id": tenant_a},
                    {"user_id": a_viewer, "department_id": a_department, "tenant_id": tenant_a},
                    {"user_id": b_admin, "department_id": b_department, "tenant_id": tenant_b},
                ],
            )
        a_document = await _seed_document(
            owner_engine, tenant_a, a_department, a_admin, profile_id, embedding_profile_id
        )
        a_other_document = await _seed_document(
            owner_engine,
            tenant_a,
            a_other_department,
            a_admin,
            profile_id,
            embedding_profile_id,
        )
        b_document = await _seed_document(
            owner_engine, tenant_b, b_department, b_admin, profile_id, embedding_profile_id
        )
        document_ids = [
            a_document.document_id,
            a_other_document.document_id,
            b_document.document_id,
        ]
        yield _IsolationFixture(
            runtime_engine=runtime_engine,
            owner_engine=owner_engine,
            tenant_a_viewer=_Actor(tenant_a, a_viewer, "viewer"),
            tenant_a_admin=_Actor(tenant_a, a_admin, "tenant_admin"),
            tenant_b_admin=_Actor(tenant_b, b_admin, "tenant_admin"),
            tenant_a_department_id=a_department,
            tenant_b_department_id=b_department,
            tenant_a_department_document=a_document,
            tenant_a_other_department_document=a_other_document,
            tenant_b_document=b_document,
        )
    finally:
        async with owner_engine.begin() as connection:
            if document_ids:
                await connection.execute(
                    delete(DocumentModel).where(DocumentModel.id.in_(document_ids))
                )
            await connection.execute(
                delete(UserModel).where(UserModel.id.in_([a_admin, a_viewer, b_admin]))
            )
            await connection.execute(
                delete(DepartmentModel).where(
                    DepartmentModel.id.in_([a_department, a_other_department, b_department])
                )
            )
            await connection.execute(
                delete(TenantModel).where(TenantModel.id.in_([tenant_a, tenant_b]))
            )
        await runtime_engine.dispose()
        await owner_engine.dispose()


async def _set_scope(connection: object, actor: _Actor) -> None:
    """Set the three transaction-local context values expected by RLS policies."""
    from sqlalchemy.ext.asyncio import AsyncConnection

    assert isinstance(connection, AsyncConnection)
    for name, value in (
        ("app.tenant_id", str(actor.tenant_id)),
        ("app.user_id", str(actor.user_id)),
        ("app.role", actor.role),
    ):
        await connection.execute(
            text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value}
        )


_PROTECTED_ROWS = (
    ("documents", "id", "document_id"),
    ("document_departments", "document_id", "document_id"),
    ("document_versions", "id", "version_id"),
    ("processing_jobs", "id", "job_id"),
    ("extracted_documents", "document_version_id", "version_id"),
    ("entities", "id", "entity_id"),
    ("index_generations", "id", "generation_id"),
    ("chunks", "id", "chunk_id"),
    ("chunk_embeddings", "id", "embedding_id"),
)


async def _visible_rows(connection: object, rows: _DocumentRows) -> set[str]:
    """Read each protected table directly, without application repository filters."""
    from sqlalchemy.ext.asyncio import AsyncConnection

    assert isinstance(connection, AsyncConnection)
    visible: set[str] = set()
    for table, key, attribute in _PROTECTED_ROWS:
        statement = text(f"SELECT 1 FROM {table} WHERE {key} = :row_id").bindparams(
            bindparam("row_id", type_=Uuid(as_uuid=True))
        )
        if await connection.scalar(statement, {"row_id": getattr(rows, attribute)}) is not None:
            visible.add(table)
    return visible


@pytest.mark.anyio
async def test_direct_reads_respect_tenant_department_and_admin_scope(
    isolation_rows: _IsolationFixture,
) -> None:
    """All derived records inherit document authorization under direct SQL."""
    fixture = isolation_rows
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            own = await _visible_rows(connection, fixture.tenant_a_department_document)
            denied_department = await _visible_rows(
                connection, fixture.tenant_a_other_department_document
            )
            denied_tenant = await _visible_rows(connection, fixture.tenant_b_document)
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_admin)
            admin_other_department = await _visible_rows(
                connection, fixture.tenant_a_other_department_document
            )
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_b_admin)
            other_tenant_own = await _visible_rows(connection, fixture.tenant_b_document)

    expected = {table for table, _, _ in _PROTECTED_ROWS}
    assert own == expected
    assert denied_department == set()
    assert denied_tenant == set()
    assert admin_other_department == expected
    assert other_tenant_own == expected


@pytest.mark.anyio
async def test_dedicated_login_roles_have_distinct_table_capabilities(
    isolation_rows: _IsolationFixture,
) -> None:
    """API reads, authentication, and workers use distinct non-owner grants."""
    settings = _DatabaseTestSettings()
    passwords = (
        settings.database_read_password,
        settings.database_auth_password,
        settings.database_worker_password,
    )
    if not all(passwords):
        pytest.skip("Run database role bootstrap with the local role passwords")
    _, test_runtime_url = _test_urls()
    login_roles = (
        ("di_api_read_login", passwords[0]),
        ("di_auth_login", passwords[1]),
        ("di_worker_login", passwords[2]),
    )
    engines = [
        create_async_engine(test_runtime_url.set(username=role, password=password))
        for role, password in login_roles
    ]
    fixture = isolation_rows
    try:
        async with engines[0].connect() as connection:
            async with connection.begin():
                await _set_scope(connection, fixture.tenant_a_viewer)
                assert (
                    await connection.scalar(
                        select(ChunkModel.id).where(
                            ChunkModel.id == fixture.tenant_a_department_document.chunk_id
                        )
                    )
                    == fixture.tenant_a_department_document.chunk_id
                )
                assert (
                    await connection.scalar(
                        select(ChunkModel.id).where(
                            ChunkModel.id == fixture.tenant_b_document.chunk_id
                        )
                    )
                    is None
                )
            transaction = await connection.begin()
            try:
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        DocumentModel.__table__.insert().values(
                            id=uuid4(),
                            tenant_id=fixture.tenant_a_viewer.tenant_id,
                            title="reader cannot insert",
                            created_by=fixture.tenant_a_viewer.user_id,
                        )
                    )
            finally:
                await transaction.rollback()
        async with engines[1].connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(DBAPIError):
                    await connection.scalar(select(ChunkModel.id).limit(1))
            finally:
                await transaction.rollback()
        async with engines[2].connect() as connection:
            async with connection.begin():
                assert await connection.scalar(select(DocumentVersionModel.id).limit(1)) is None
            async with connection.begin():
                await connection.execute(
                    text("SELECT set_config('app.job_id', :job_id, true)"),
                    {"job_id": str(fixture.tenant_a_department_document.job_id)},
                )
                assert (
                    await connection.scalar(
                        select(DocumentVersionModel.id).where(
                            DocumentVersionModel.id
                            == fixture.tenant_a_department_document.version_id
                        )
                    )
                    == fixture.tenant_a_department_document.version_id
                )
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.anyio
async def test_editor_can_assign_departments_only_in_creation_transaction(
    isolation_rows: _IsolationFixture,
) -> None:
    """The database itself closes the initial-assignment window at commit."""
    fixture = isolation_rows
    editor_id, document_id = uuid4(), uuid4()
    async with fixture.owner_engine.begin() as connection:
        other_department_id = await connection.scalar(
            select(DepartmentModel.id).where(
                DepartmentModel.tenant_id == fixture.tenant_a_viewer.tenant_id,
                DepartmentModel.id != fixture.tenant_a_department_id,
            )
        )
        assert other_department_id is not None
        await connection.execute(
            UserModel.__table__.insert().values(
                id=editor_id,
                tenant_id=fixture.tenant_a_viewer.tenant_id,
                email=f"editor-{editor_id}@example.test",
                display_name="Editor",
                password_hash="test",
                role="editor",
            )
        )
        await connection.execute(
            UserDepartmentModel.__table__.insert(),
            [
                {
                    "user_id": editor_id,
                    "department_id": department_id,
                    "tenant_id": fixture.tenant_a_viewer.tenant_id,
                }
                for department_id in (fixture.tenant_a_department_id, other_department_id)
            ],
        )
    editor = _Actor(fixture.tenant_a_viewer.tenant_id, editor_id, "editor")
    try:
        async with fixture.runtime_engine.begin() as connection:
            await _set_scope(connection, editor)
            await connection.execute(
                DocumentModel.__table__.insert().values(
                    id=document_id,
                    tenant_id=editor.tenant_id,
                    title="new editor document",
                    created_by=editor_id,
                )
            )
            await connection.execute(
                DocumentDepartmentModel.__table__.insert().values(
                    document_id=document_id,
                    tenant_id=editor.tenant_id,
                    department_id=fixture.tenant_a_department_id,
                )
            )
        async with fixture.runtime_engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await _set_scope(connection, editor)
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        DocumentDepartmentModel.__table__.insert().values(
                            document_id=document_id,
                            tenant_id=editor.tenant_id,
                            department_id=other_department_id,
                        )
                    )
            finally:
                await transaction.rollback()
    finally:
        async with fixture.owner_engine.begin() as connection:
            await connection.execute(delete(DocumentModel).where(DocumentModel.id == document_id))
            await connection.execute(delete(UserModel).where(UserModel.id == editor_id))


@pytest.mark.anyio
async def test_api_write_role_can_flush_new_document_and_version(
    isolation_rows: _IsolationFixture,
) -> None:
    """Normal ORM flush ordering must work with initial assignment RLS checks."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    settings = _DatabaseTestSettings()
    if not settings.database_write_password:
        pytest.skip("Run database role bootstrap with the local write password")
    _, test_url = _test_urls()
    engine = create_async_engine(
        test_url.set(username="di_api_write_login", password=settings.database_write_password)
    )
    document_id, version_id = uuid4(), uuid4()
    fixture = isolation_rows
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.info["rls_actor_id"] = fixture.tenant_a_admin.user_id
            async with session.begin():
                session.add(
                    DocumentModel(
                        id=document_id,
                        tenant_id=fixture.tenant_a_admin.tenant_id,
                        title="new document",
                        created_by=fixture.tenant_a_admin.user_id,
                    )
                )
                session.add(
                    DocumentDepartmentModel(
                        document_id=document_id,
                        tenant_id=fixture.tenant_a_admin.tenant_id,
                        department_id=fixture.tenant_a_department_id,
                    )
                )
                session.add(
                    DocumentVersionModel(
                        id=version_id,
                        document_id=document_id,
                        tenant_id=fixture.tenant_a_admin.tenant_id,
                        version_number=1,
                        original_filename="new.pdf",
                        object_key=f"test/{version_id}",
                        media_type="application/pdf",
                        size_bytes=8,
                        content_sha256=b"0" * 32,
                        status="stored",
                        created_by=fixture.tenant_a_admin.user_id,
                    )
                )
        async with fixture.owner_engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(DocumentVersionModel.id).where(DocumentVersionModel.id == version_id)
                )
                == version_id
            )
    finally:
        async with fixture.owner_engine.begin() as connection:
            await connection.execute(delete(DocumentModel).where(DocumentModel.id == document_id))
        await engine.dispose()


@pytest.mark.anyio
async def test_query_route_never_sends_denied_passages_to_generation(
    isolation_rows: _IsolationFixture,
) -> None:
    """An authenticated HTTP query reaches SQL retrieval with the current RLS scope."""
    from collections.abc import AsyncIterator
    from typing import Annotated

    from fastapi import Depends
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from document_insight.api.app import create_app
    from document_insight.api.dependencies import (
        get_auth_db_session,
        get_current_user,
        get_db_session,
        get_query_preparation_service,
    )
    from document_insight.application.auth.models import (
        AuthorizationContext,
        UserCredentials,
        UserRole,
    )
    from document_insight.application.query.profile_resolver import QueryProfileResolver
    from document_insight.application.query.service import QueryPreparationService
    from document_insight.config import get_settings
    from document_insight.infrastructure.active_profile.repository import (
        SqlAlchemyActiveProfileRepository,
    )
    from document_insight.infrastructure.capability_profile.repository import (
        SqlAlchemyCapabilityProfileRepository,
    )
    from document_insight.infrastructure.configuration_snapshot.repository import (
        SqlAlchemyConfigurationSnapshotRepository,
    )
    from document_insight.infrastructure.department.repository import SqlAlchemyDepartmentRepository
    from document_insight.infrastructure.generation.protocol import GroundedAnswer
    from document_insight.infrastructure.query_profile.repository import (
        SqlAlchemyQueryProfileRepository,
    )
    from document_insight.infrastructure.reranker.protocol import RerankScore
    from document_insight.infrastructure.retrieval.repository import (
        SqlAlchemyAuthorizedRetrievalRepository,
    )
    from document_insight.infrastructure.security.token_issuer import JwtTokenIssuer

    settings = _DatabaseTestSettings()
    if not settings.database_read_password or not settings.database_auth_password:
        pytest.skip("Run database role bootstrap with the local role passwords")
    _, test_url = _test_urls()
    read_engine = create_async_engine(
        test_url.set(username="di_api_read_login", password=settings.database_read_password)
    )
    auth_engine = create_async_engine(
        test_url.set(username="di_auth_login", password=settings.database_auth_password)
    )
    read_sessions = async_sessionmaker(read_engine, expire_on_commit=False)
    auth_sessions = async_sessionmaker(auth_engine, expire_on_commit=False)
    generated_from: list[UUID] = []

    class _Embedder:
        async def embed(
            self, texts: object, configuration: object
        ) -> tuple[tuple[float, ...], ...]:
            return ((0.1, 0.2, 0.3),)

    class _Embedders:
        def create(self, configuration: object) -> _Embedder:
            return _Embedder()

    class _Reranker:
        async def rerank(
            self, question: str, candidates: object, configuration: object
        ) -> tuple[RerankScore, ...]:
            return tuple(RerankScore(item.chunk_id, 0.9) for item in candidates)

    class _Rerankers:
        def create(self, configuration: object) -> _Reranker:
            return _Reranker()

    class _Generator:
        async def generate(
            self, question: str, passages: object, configuration: object
        ) -> GroundedAnswer:
            generated_from.extend(passage.chunk_id for passage in passages)
            return GroundedAnswer("Authorized fixture passage.", (passages[0].chunk_id,))

    class _Generators:
        def create(self, configuration: object) -> _Generator:
            return _Generator()

    async def read_session() -> AsyncIterator[AsyncSession]:
        async with read_sessions() as session:
            yield session

    async def auth_session() -> AsyncIterator[AsyncSession]:
        async with auth_sessions() as session:
            yield session

    def query_service(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        actor: Annotated[AuthorizationContext, Depends(get_current_user)],
    ) -> QueryPreparationService:
        session.info["rls_actor_id"] = actor.user_id
        return QueryPreparationService(
            active_profiles=SqlAlchemyActiveProfileRepository(session),
            profile_resolver=QueryProfileResolver(
                SqlAlchemyQueryProfileRepository(session),
                SqlAlchemyCapabilityProfileRepository(session),
                SqlAlchemyConfigurationSnapshotRepository(session),
            ),
            departments=SqlAlchemyDepartmentRepository(session),
            retrieval=SqlAlchemyAuthorizedRetrievalRepository(session),
            embedders=_Embedders(),
            rerankers=_Rerankers(),
            generators=_Generators(),
        )

    app = create_app()
    app.dependency_overrides[get_db_session] = read_session
    app.dependency_overrides[get_auth_db_session] = auth_session
    app.dependency_overrides[get_query_preparation_service] = query_service
    actor = isolation_rows.tenant_a_viewer
    configuration = get_settings()
    token = (
        JwtTokenIssuer(
            configuration.jwt_secret_key,
            configuration.jwt_algorithm,
            configuration.jwt_issuer,
            configuration.jwt_audience,
            configuration.jwt_access_token_expire_minutes,
        )
        .issue(
            UserCredentials(
                actor.user_id,
                actor.tenant_id,
                (isolation_rows.tenant_a_department_id,),
                "viewer@example.test",
                "Viewer",
                UserRole.VIEWER,
                "test",
            )
        )
        .value
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/query",
                headers={"Authorization": f"Bearer {token}"},
                json={"question": "shared rls fixture passage", "top_k": 5},
            )
        assert response.status_code == 200
        assert generated_from == [isolation_rows.tenant_a_department_document.chunk_id]
        assert [source["chunk_id"] for source in response.json()["sources"]] == [
            str(isolation_rows.tenant_a_department_document.chunk_id)
        ]
    finally:
        await read_engine.dispose()
        await auth_engine.dispose()


@pytest.mark.anyio
async def test_identity_rows_cannot_cross_tenant_boundary(
    isolation_rows: _IsolationFixture,
) -> None:
    """The same runtime role cannot read another tenant's identity records."""
    fixture = isolation_rows
    identities = (
        ("tenants", "id", fixture.tenant_a_viewer.tenant_id, fixture.tenant_b_admin.tenant_id),
        ("departments", "id", fixture.tenant_a_department_id, fixture.tenant_b_department_id),
        ("users", "id", fixture.tenant_a_viewer.user_id, fixture.tenant_b_admin.user_id),
        (
            "user_departments",
            "user_id",
            fixture.tenant_a_viewer.user_id,
            fixture.tenant_b_admin.user_id,
        ),
    )
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            for table, key, own_id, foreign_id in identities:
                statement = text(f"SELECT 1 FROM {table} WHERE {key} = :row_id").bindparams(
                    bindparam("row_id", type_=Uuid(as_uuid=True))
                )
                assert await connection.scalar(statement, {"row_id": own_id}) == 1
                assert await connection.scalar(statement, {"row_id": foreign_id}) is None


@pytest.mark.anyio
async def test_missing_context_and_reused_connection_do_not_leak_rows(
    isolation_rows: _IsolationFixture,
) -> None:
    """Transaction-local scope must disappear before a pooled connection is reused."""
    fixture = isolation_rows
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            without_context = await _visible_rows(connection, fixture.tenant_a_department_document)
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            with_context = await _visible_rows(connection, fixture.tenant_a_department_document)
        async with connection.begin():
            after_context = await _visible_rows(connection, fixture.tenant_a_department_document)
    assert without_context == set()
    assert with_context == {table for table, _, _ in _PROTECTED_ROWS}
    assert after_context == set()


@pytest.mark.anyio
async def test_revoked_membership_removes_direct_read_access(
    isolation_rows: _IsolationFixture,
) -> None:
    """Policies must consult current membership, not a stale department claim."""
    fixture = isolation_rows
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            before = await _visible_rows(connection, fixture.tenant_a_department_document)
    async with fixture.owner_engine.begin() as connection:
        await connection.execute(
            delete(UserDepartmentModel).where(
                UserDepartmentModel.user_id == fixture.tenant_a_viewer.user_id
            )
        )
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            after = await _visible_rows(connection, fixture.tenant_a_department_document)
    assert before == {table for table, _, _ in _PROTECTED_ROWS}
    assert after == set()


@pytest.mark.anyio
async def test_direct_writes_cannot_cross_tenant_or_department(
    isolation_rows: _IsolationFixture,
) -> None:
    """A scoped viewer cannot modify documents outside their permitted scope."""
    fixture = isolation_rows
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            other_department = await connection.execute(
                update(DocumentModel)
                .where(DocumentModel.id == fixture.tenant_a_other_department_document.document_id)
                .values(title="unauthorized")
            )
            other_tenant = await connection.execute(
                update(DocumentModel)
                .where(DocumentModel.id == fixture.tenant_b_document.document_id)
                .values(title="unauthorized")
            )
            assert other_department.rowcount == 0
            assert other_tenant.rowcount == 0


@pytest.mark.anyio
async def test_cross_tenant_insert_is_rejected_by_policy(
    isolation_rows: _IsolationFixture,
) -> None:
    """A valid foreign-tenant document row cannot be inserted under another tenant's scope."""
    fixture = isolation_rows
    async with fixture.runtime_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(DBAPIError):
                await _set_scope(connection, fixture.tenant_a_viewer)
                await connection.execute(
                    DocumentModel.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=fixture.tenant_b_admin.tenant_id,
                        title="unauthorized",
                        created_by=fixture.tenant_b_admin.user_id,
                    )
                )
        finally:
            await transaction.rollback()


@pytest.mark.anyio
async def test_viewer_cannot_change_document_department_assignment(
    isolation_rows: _IsolationFixture,
) -> None:
    """Only tenant administrators may change the source-of-truth assignment table."""
    fixture = isolation_rows
    document_id = fixture.tenant_a_department_document.document_id
    async with fixture.runtime_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _set_scope(connection, fixture.tenant_a_viewer)
            removed = await connection.execute(
                delete(DocumentDepartmentModel).where(
                    DocumentDepartmentModel.document_id == document_id
                )
            )
            assert removed.rowcount == 0
        finally:
            await transaction.rollback()


@pytest.mark.anyio
async def test_lexical_and_vector_ranking_never_see_denied_passages(
    isolation_rows: _IsolationFixture,
) -> None:
    """Search scores must be computed only for permitted document passages."""
    fixture = isolation_rows
    row_ids = {
        "own": fixture.tenant_a_department_document.chunk_id,
        "department": fixture.tenant_a_other_department_document.chunk_id,
        "tenant": fixture.tenant_b_document.chunk_id,
    }
    row_binds = [bindparam(name, type_=Uuid(as_uuid=True)) for name in row_ids]
    async with fixture.runtime_engine.connect() as connection:
        async with connection.begin():
            await _set_scope(connection, fixture.tenant_a_viewer)
            lexical = (
                (
                    await connection.execute(
                        text(
                            "SELECT id FROM chunks "
                            "WHERE search_vector @@ websearch_to_tsquery('simple', 'rls fixture') "
                            "AND id IN (:own, :department, :tenant) "
                            "ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('simple', 'rls fixture')) DESC"
                        ).bindparams(*row_binds),
                        row_ids,
                    )
                )
                .scalars()
                .all()
            )
            vector = (
                (
                    await connection.execute(
                        text(
                            "SELECT c.id FROM chunks AS c "
                            "JOIN chunk_embeddings AS e ON e.chunk_id = c.id "
                            "WHERE c.id IN (:own, :department, :tenant) "
                            "ORDER BY e.embedding <=> '[0.1,0.2,0.3]'::vector"
                        ).bindparams(*row_binds),
                        row_ids,
                    )
                )
                .scalars()
                .all()
            )
    expected = {fixture.tenant_a_department_document.chunk_id}
    assert set(lexical) == expected
    assert set(vector) == expected
