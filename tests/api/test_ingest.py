"""Authenticated document storage endpoint tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from document_insight.api.app import create_app
from document_insight.api.dependencies import get_object_storage
from document_insight.config import Settings, get_settings
from document_insight.domain.auth import StoredUser, UserRole
from document_insight.infrastructure.database.base import Base
from document_insight.infrastructure.database.models import (
    DepartmentModel,
    DocumentDepartmentModel,
    DocumentModel,
    DocumentVersionModel,
    TenantModel,
    UserDepartmentModel,
    UserModel,
)
from document_insight.infrastructure.database.session import get_db_session
from document_insight.infrastructure.security import JwtTokenIssuer


@dataclass
class FakeObjectStorage:
    """Capture immutable object operations without network access."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@dataclass(frozen=True)
class IngestContext:
    """Resources and tenant identifiers used by ingestion authorization tests."""

    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    storage: FakeObjectStorage
    settings: Settings
    tenant_id: UUID
    general_department_id: UUID
    legal_department_id: UUID


@pytest.fixture
def anyio_backend() -> str:
    """Run async API tests on asyncio."""
    return "asyncio"


@pytest.fixture
async def ingest_context() -> AsyncIterator[IngestContext]:
    """Create an authenticated API backed by isolated database and object storage fakes."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant_id = uuid4()
    department_id = uuid4()
    legal_department_id = uuid4()
    user_id = uuid4()
    async with session_factory.begin() as session:
        session.add(TenantModel(id=tenant_id, name="Example Tenant"))
        session.add(DepartmentModel(id=department_id, tenant_id=tenant_id, name="General"))
        session.add(DepartmentModel(id=legal_department_id, tenant_id=tenant_id, name="Legal"))
        session.add(
            UserModel(
                id=user_id,
                tenant_id=tenant_id,
                email="admin@example.com",
                display_name="Tenant Admin",
                password_hash="unused-in-ingestion-test",
                role=UserRole.TENANT_ADMIN.value,
            )
        )
        session.add(
            UserDepartmentModel(
                user_id=user_id,
                department_id=department_id,
                tenant_id=tenant_id,
            )
        )

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret_key=SecretStr("test-secret-key-that-is-long-enough"),
    )
    token = JwtTokenIssuer(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.jwt_access_token_expire_minutes,
    ).issue(
        StoredUser(
            user_id=user_id,
            tenant_id=tenant_id,
            department_ids=(department_id,),
            email="admin@example.com",
            display_name="Tenant Admin",
            role=UserRole.TENANT_ADMIN,
            password_hash="unused-in-ingestion-test",
        )
    )
    storage = FakeObjectStorage()
    application = create_app()

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_storage] = lambda: storage

    transport = ASGITransport(app=application)
    headers = {"Authorization": f"Bearer {token.value}"}
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=headers,
    ) as client:
        yield IngestContext(
            client=client,
            session_factory=session_factory,
            storage=storage,
            settings=settings,
            tenant_id=tenant_id,
            general_department_id=department_id,
            legal_department_id=legal_department_id,
        )

    await engine.dispose()


async def create_user_token(
    context: IngestContext,
    role: UserRole,
    department_ids: tuple[UUID, ...],
) -> str:
    """Persist a user with multiple memberships and issue its access token."""
    user_id = uuid4()
    async with context.session_factory.begin() as session:
        session.add(
            UserModel(
                id=user_id,
                tenant_id=context.tenant_id,
                email=f"{role.value}-{user_id}@example.com",
                display_name=role.value,
                password_hash="unused-in-ingestion-test",
                role=role.value,
            )
        )
        session.add_all(
            UserDepartmentModel(
                user_id=user_id,
                department_id=department_id,
                tenant_id=context.tenant_id,
            )
            for department_id in department_ids
        )

    return (
        JwtTokenIssuer(
            secret_key=context.settings.jwt_secret_key,
            algorithm=context.settings.jwt_algorithm,
            issuer=context.settings.jwt_issuer,
            audience=context.settings.jwt_audience,
            expire_minutes=context.settings.jwt_access_token_expire_minutes,
        )
        .issue(
            StoredUser(
                user_id=user_id,
                tenant_id=context.tenant_id,
                department_ids=department_ids,
                email=f"{role.value}-{user_id}@example.com",
                display_name=role.value,
                role=role,
                password_hash="unused-in-ingestion-test",
            )
        )
        .value
    )


@pytest.mark.anyio
async def test_ingest_stores_original_and_document_metadata(
    ingest_context: IngestContext,
) -> None:
    """A valid authenticated PDF is stored as version one and returns the interim 203."""
    client = ingest_context.client
    session_factory = ingest_context.session_factory
    storage = ingest_context.storage
    content = b"%PDF-1.7\nexample"

    response = await client.post(
        "/ingest",
        files={"file": ("contract.pdf", content, "application/pdf")},
    )

    assert response.status_code == 203
    body = response.json()
    assert body["status"] == "stored"
    assert body["version_number"] == 1
    assert len(storage.objects) == 1
    object_key, stored_object = next(iter(storage.objects.items()))
    assert object_key.startswith("tenants/")
    assert stored_object == (content, "application/pdf")

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentModel)) == 1
        version = await session.scalar(select(DocumentVersionModel))
        assignment = await session.scalar(select(DocumentDepartmentModel))

    assert version is not None
    assert str(version.id) == body["document_version_id"]
    assert version.object_key == object_key
    assert version.status == "stored"
    assert assignment is not None
    assert str(assignment.document_id) == body["document_id"]


@pytest.mark.anyio
async def test_ingest_existing_document_creates_next_immutable_version(
    ingest_context: IngestContext,
) -> None:
    """Supplying a document ID stores a second object under the stable logical document."""
    client = ingest_context.client
    session_factory = ingest_context.session_factory
    storage = ingest_context.storage
    first = await client.post(
        "/ingest",
        files={"file": ("contract.pdf", b"%PDF-1.7\nv1", "application/pdf")},
    )

    second = await client.post(
        "/ingest",
        data={"document_id": first.json()["document_id"]},
        files={"file": ("contract.pdf", b"%PDF-1.7\nv2", "application/pdf")},
    )

    assert second.status_code == 203
    assert second.json()["document_id"] == first.json()["document_id"]
    assert second.json()["version_number"] == 2
    assert len(storage.objects) == 2
    async with session_factory() as session:
        versions = tuple(
            await session.scalars(
                select(DocumentVersionModel).order_by(DocumentVersionModel.version_number)
            )
        )
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].object_key != versions[1].object_key


@pytest.mark.anyio
async def test_ingest_requires_a_valid_bearer_token(
    ingest_context: IngestContext,
) -> None:
    """Unauthenticated uploads are rejected before object storage is called."""
    client = ingest_context.client
    storage = ingest_context.storage

    response = await client.post(
        "/ingest",
        headers={"Authorization": ""},
        files={"file": ("contract.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_access_token"
    assert storage.objects == {}


@pytest.mark.anyio
async def test_ingest_rejects_mismatched_content_type_and_signature(
    ingest_context: IngestContext,
) -> None:
    """Declared MIME type cannot disguise a different supported file signature."""
    client = ingest_context.client
    storage = ingest_context.storage

    response = await client.post(
        "/ingest",
        files={"file": ("fake.png", b"%PDF-1.7\n", "image/png")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_document_type"
    assert storage.objects == {}


@pytest.mark.anyio
async def test_tenant_admin_can_create_document_in_any_tenant_department(
    ingest_context: IngestContext,
) -> None:
    """An administrator may select a tenant department outside their own memberships."""
    response = await ingest_context.client.post(
        "/ingest",
        data={"department_ids": str(ingest_context.legal_department_id)},
        files={"file": ("legal.pdf", b"%PDF-1.7\nlegal", "application/pdf")},
    )

    assert response.status_code == 203
    async with ingest_context.session_factory() as session:
        assignment = await session.scalar(
            select(DocumentDepartmentModel).where(
                DocumentDepartmentModel.document_id == UUID(response.json()["document_id"])
            )
        )
    assert assignment is not None
    assert assignment.department_id == ingest_context.legal_department_id


@pytest.mark.anyio
async def test_editor_can_select_subset_of_own_departments_only(
    ingest_context: IngestContext,
) -> None:
    """An editor with multiple memberships may narrow but never broaden document scope."""
    editor_token = await create_user_token(
        ingest_context,
        UserRole.EDITOR,
        (ingest_context.general_department_id, ingest_context.legal_department_id),
    )
    permitted = await ingest_context.client.post(
        "/ingest",
        headers={"Authorization": f"Bearer {editor_token}"},
        data={"department_ids": str(ingest_context.legal_department_id)},
        files={"file": ("legal.pdf", b"%PDF-1.7\nlegal", "application/pdf")},
    )

    outside_department_id = uuid4()
    async with ingest_context.session_factory.begin() as session:
        session.add(
            DepartmentModel(
                id=outside_department_id,
                tenant_id=ingest_context.tenant_id,
                name="Finance",
            )
        )
    forbidden = await ingest_context.client.post(
        "/ingest",
        headers={"Authorization": f"Bearer {editor_token}"},
        data={"department_ids": str(outside_department_id)},
        files={"file": ("finance.pdf", b"%PDF-1.7\nfinance", "application/pdf")},
    )

    assert permitted.status_code == 203
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "ingestion_forbidden"
    assert len(ingest_context.storage.objects) == 1


@pytest.mark.anyio
async def test_viewer_cannot_ingest_documents(ingest_context: IngestContext) -> None:
    """Viewer role is denied before any object or metadata is written."""
    viewer_token = await create_user_token(
        ingest_context,
        UserRole.VIEWER,
        (ingest_context.general_department_id,),
    )

    response = await ingest_context.client.post(
        "/ingest",
        headers={"Authorization": f"Bearer {viewer_token}"},
        files={"file": ("read-only.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ingestion_forbidden"
    assert ingest_context.storage.objects == {}
