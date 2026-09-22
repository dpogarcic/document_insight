"""Authenticated document storage endpoint tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from document_insight.api.app import create_app
from document_insight.api.dependencies import get_object_storage, get_processing_queue
from document_insight.application.auth.models import UserCredentials, UserRole
from document_insight.application.ingestion.exceptions import QueueUnavailableError
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.active_profile.model import ActiveProfileModel
from document_insight.infrastructure.capability_profile.model import CapabilityProfileModel
from document_insight.infrastructure.configuration_snapshot.model import ConfigurationSnapshotModel
from document_insight.infrastructure.database.base import Base
from document_insight.infrastructure.database.session import get_db_session
from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_version.model import DocumentVersionModel
from document_insight.infrastructure.index_generation.model import IndexGenerationModel
from document_insight.infrastructure.ingestion_profile.model import IngestionProfileModel
from document_insight.infrastructure.job.model import JobModel
from document_insight.infrastructure.security.token_issuer import JwtTokenIssuer
from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user_department.model import UserDepartmentModel


@dataclass
class FakeObjectStorage:
    """Capture immutable object operations without network access."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = (content, content_type)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@dataclass
class FakeProcessingQueue:
    """Capture queue publication without requiring Redis in API tests."""

    published: list[tuple[UUID, UUID]] = field(default_factory=list)
    unavailable: bool = False

    async def enqueue_ingestion(self, job_id: UUID, correlation_id: UUID) -> None:
        if self.unavailable:
            raise QueueUnavailableError
        self.published.append((job_id, correlation_id))


@dataclass(frozen=True)
class IngestContext:
    """Resources and tenant identifiers used by ingestion authorization tests."""

    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    storage: FakeObjectStorage
    processing_queue: FakeProcessingQueue
    settings: Settings
    tenant_id: UUID
    general_department_id: UUID
    legal_department_id: UUID
    ingestion_profile_id: UUID


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
    snapshot_ids = {
        capability: uuid4() for capability in ("ner", "chunking", "lexical", "embedding")
    }
    profile_ids = {capability: uuid4() for capability in snapshot_ids}
    ingestion_profile_id = uuid4()
    async with session_factory.begin() as session:
        session.add_all(
            ConfigurationSnapshotModel(
                id=snapshot_ids[capability],
                capability=capability,
                schema_version=1,
                fingerprint=f"{capability}-test-fingerprint",
                configuration_json={},
            )
            for capability in snapshot_ids
        )
        session.add_all(
            CapabilityProfileModel(
                id=profile_ids[capability],
                capability=capability,
                name=f"{capability}-test-v1",
                configuration_snapshot_id=snapshot_ids[capability],
                status="validated",
            )
            for capability in snapshot_ids
        )
        session.add(
            IngestionProfileModel(
                id=ingestion_profile_id,
                ner_profile_id=profile_ids["ner"],
                chunking_profile_id=profile_ids["chunking"],
                lexical_profile_id=profile_ids["lexical"],
                embedding_profile_id=profile_ids["embedding"],
            )
        )
        session.add(
            ActiveProfileModel(
                id=uuid4(),
                scope="platform",
                profile_kind="ingestion",
                ingestion_profile_id=ingestion_profile_id,
                revision=1,
            )
        )
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
        mistral_api_key=SecretStr("test-mistral-key"),
    )
    token = JwtTokenIssuer(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.jwt_access_token_expire_minutes,
    ).issue(
        UserCredentials(
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
    processing_queue = FakeProcessingQueue()
    application = create_app()

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_storage] = lambda: storage
    application.dependency_overrides[get_processing_queue] = lambda: processing_queue

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
            processing_queue=processing_queue,
            settings=settings,
            tenant_id=tenant_id,
            general_department_id=department_id,
            legal_department_id=legal_department_id,
            ingestion_profile_id=ingestion_profile_id,
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
            UserCredentials(
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
    """A valid authenticated PDF is stored and queued as version one."""
    client = ingest_context.client
    session_factory = ingest_context.session_factory
    storage = ingest_context.storage
    content = b"%PDF-1.7\nexample"

    response = await client.post(
        "/ingest",
        files={"file": ("contract.pdf", content, "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "stored"
    assert body["job_status"] == "queued"
    assert body["version_number"] == 1
    assert len(storage.objects) == 1
    object_key, stored_object = next(iter(storage.objects.items()))
    assert object_key.startswith("tenants/")
    assert stored_object == (content, "application/pdf")

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(DocumentModel)) == 1
        version = await session.scalar(select(DocumentVersionModel))
        job = await session.scalar(select(JobModel))
        assignment = await session.scalar(select(DocumentDepartmentModel))

    assert version is not None
    assert str(version.id) == body["document_version_id"]
    assert version.object_key == object_key
    assert version.status == "stored"
    assert job is not None
    assert str(job.id) == body["job_id"]
    assert job.document_version_id == version.id
    assert job.status == "queued"
    assert job.attempt_count == 0
    assert job.enqueued_at is not None
    assert str(job.correlation_id) == response.headers["x-correlation-id"]
    assert job.idempotency_key != job.id
    assert job.ingestion_profile_id == ingest_context.ingestion_profile_id
    assert job.index_generation_id is not None
    async with session_factory() as generation_session:
        generation = await generation_session.scalar(
            select(IndexGenerationModel).where(IndexGenerationModel.id == job.index_generation_id)
        )
    assert generation is not None
    assert generation.ingestion_profile_id == ingest_context.ingestion_profile_id
    assert ingest_context.processing_queue.published == [
        (UUID(body["job_id"]), UUID(response.headers["x-correlation-id"]))
    ]
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

    assert second.status_code == 202
    assert second.json()["document_id"] == first.json()["document_id"]
    assert second.json()["version_number"] == 2
    assert len(storage.objects) == 2
    async with session_factory() as session:
        versions = tuple(
            await session.scalars(
                select(DocumentVersionModel).order_by(DocumentVersionModel.version_number)
            )
        )
        jobs = tuple(await session.scalars(select(JobModel).order_by(JobModel.created_at)))
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].object_key != versions[1].object_key
    assert len(jobs) == 2
    assert {job.document_version_id for job in jobs} == {version.id for version in versions}


@pytest.mark.anyio
async def test_document_library_returns_authorized_documents_and_departments(
    ingest_context: IngestContext,
) -> None:
    """The library exposes latest-version metadata and tenant department display names."""
    created = await ingest_context.client.post(
        "/ingest",
        data={"department_ids": str(ingest_context.legal_department_id)},
        files={"file": ("legal.pdf", b"%PDF-1.7\nlegal", "application/pdf")},
    )
    assert created.status_code == 202

    response = await ingest_context.client.get("/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["departments"] == [
        {"department_id": str(ingest_context.general_department_id), "name": "General"},
        {"department_id": str(ingest_context.legal_department_id), "name": "Legal"},
    ]
    assert body["documents"] == [
        {
            "document_id": created.json()["document_id"],
            "title": "legal.pdf",
            "departments": [
                {"department_id": str(ingest_context.legal_department_id), "name": "Legal"}
            ],
            "current_ready_version_id": None,
            "latest_version": {
                "document_version_id": created.json()["document_version_id"],
                "version_number": 1,
                "original_filename": "legal.pdf",
                "status": "stored",
                "created_at": body["documents"][0]["latest_version"]["created_at"],
            },
            "versions": [
                {
                    "document_version_id": created.json()["document_version_id"],
                    "version_number": 1,
                    "original_filename": "legal.pdf",
                    "status": "stored",
                    "created_at": body["documents"][0]["latest_version"]["created_at"],
                }
            ],
            "created_at": body["documents"][0]["created_at"],
        }
    ]


@pytest.mark.anyio
async def test_document_library_excludes_documents_outside_an_editor_department(
    ingest_context: IngestContext,
) -> None:
    """A non-administrator cannot enumerate a document assigned only to another department."""
    created = await ingest_context.client.post(
        "/ingest",
        data={"department_ids": str(ingest_context.legal_department_id)},
        files={"file": ("legal.pdf", b"%PDF-1.7\nlegal", "application/pdf")},
    )
    assert created.status_code == 202
    editor_token = await create_user_token(
        ingest_context,
        UserRole.EDITOR,
        (ingest_context.general_department_id,),
    )

    response = await ingest_context.client.get(
        "/documents",
        headers={"Authorization": f"Bearer {editor_token}"},
    )

    assert response.status_code == 200
    assert response.json()["documents"] == []
    assert response.json()["departments"] == [
        {"department_id": str(ingest_context.general_department_id), "name": "General"}
    ]


@pytest.mark.anyio
async def test_tenant_admin_explicitly_activates_a_ready_document_version(
    ingest_context: IngestContext,
) -> None:
    """A ready update becomes searchable only after the administrator selects it."""
    created = await ingest_context.client.post(
        "/ingest",
        files={"file": ("guide.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
    )
    assert created.status_code == 202
    document_id = created.json()["document_id"]
    version_id = created.json()["document_version_id"]
    async with ingest_context.session_factory.begin() as session:
        await session.execute(
            update(DocumentVersionModel)
            .where(DocumentVersionModel.id == UUID(version_id))
            .values(status="ready")
        )

    response = await ingest_context.client.post(
        f"/documents/{document_id}/activate",
        json={"document_version_id": version_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "current_ready_version_id": version_id,
    }
    async with ingest_context.session_factory() as session:
        document = await session.scalar(
            select(DocumentModel).where(DocumentModel.id == UUID(document_id))
        )
    assert document is not None
    assert document.current_ready_version_id == UUID(version_id)


@pytest.mark.anyio
async def test_document_activation_rejects_non_ready_versions_and_editors(
    ingest_context: IngestContext,
) -> None:
    """Activation cannot accidentally expose a queued version or editor-selected version."""
    created = await ingest_context.client.post(
        "/ingest",
        files={"file": ("guide.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
    )
    document_id = created.json()["document_id"]
    version_id = created.json()["document_version_id"]
    not_ready = await ingest_context.client.post(
        f"/documents/{document_id}/activate",
        json={"document_version_id": version_id},
    )
    editor_token = await create_user_token(
        ingest_context,
        UserRole.EDITOR,
        (ingest_context.general_department_id,),
    )
    forbidden = await ingest_context.client.post(
        f"/documents/{document_id}/activate",
        headers={"Authorization": f"Bearer {editor_token}"},
        json={"document_version_id": version_id},
    )

    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "document_version_not_ready"
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "document_activation_forbidden"


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

    assert response.status_code == 202
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

    assert permitted.status_code == 202
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


@pytest.mark.anyio
async def test_ingest_keeps_durable_job_when_queue_is_unavailable(
    ingest_context: IngestContext,
) -> None:
    """A queue outage returns a safe retryable error without losing the durable job."""
    ingest_context.processing_queue.unavailable = True

    response = await ingest_context.client.post(
        "/ingest",
        files={"file": ("contract.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "queue_unavailable"
    assert len(ingest_context.storage.objects) == 1
    async with ingest_context.session_factory() as session:
        job = await session.scalar(select(JobModel))
    assert job is not None
    assert job.enqueued_at is None


@pytest.mark.anyio
async def test_get_job_returns_authoritative_pre_queue_state(
    ingest_context: IngestContext,
) -> None:
    """An authorized caller can inspect the durable job created by ingestion."""
    ingestion = await ingest_context.client.post(
        "/ingest",
        files={"file": ("contract.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    response = await ingest_context.client.get(f"/jobs/{ingestion.json()['job_id']}")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": ingestion.json()["job_id"],
        "document_id": ingestion.json()["document_id"],
        "document_version_id": ingestion.json()["document_version_id"],
        "status": "queued",
        "attempt_count": 0,
        "created_at": response.json()["created_at"],
        "updated_at": response.json()["updated_at"],
        "error_code": None,
    }


@pytest.mark.anyio
async def test_viewer_can_read_job_for_an_accessible_document(
    ingest_context: IngestContext,
) -> None:
    """Viewers may inspect jobs for documents in one of their departments."""
    ingestion = await ingest_context.client.post(
        "/ingest",
        files={"file": ("contract.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    viewer_token = await create_user_token(
        ingest_context,
        UserRole.VIEWER,
        (ingest_context.general_department_id,),
    )

    response = await ingest_context.client.get(
        f"/jobs/{ingestion.json()['job_id']}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@pytest.mark.anyio
async def test_get_job_hides_jobs_outside_department_scope(
    ingest_context: IngestContext,
) -> None:
    """An inaccessible job is indistinguishable from an unknown identifier."""
    ingestion = await ingest_context.client.post(
        "/ingest",
        files={"file": ("general.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    legal_viewer_token = await create_user_token(
        ingest_context,
        UserRole.VIEWER,
        (ingest_context.legal_department_id,),
    )

    response = await ingest_context.client.get(
        f"/jobs/{ingestion.json()['job_id']}",
        headers={"Authorization": f"Bearer {legal_viewer_token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_not_found"


@pytest.mark.anyio
async def test_get_job_requires_authentication(ingest_context: IngestContext) -> None:
    """Job state is never exposed without a valid bearer token."""
    response = await ingest_context.client.get(
        f"/jobs/{uuid4()}",
        headers={"Authorization": ""},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_access_token"


@pytest.mark.anyio
async def test_authenticated_job_id_must_be_a_uuid(ingest_context: IngestContext) -> None:
    """Authenticated malformed job identifiers fail transport validation."""
    response = await ingest_context.client.get("/jobs/not-a-uuid")

    assert response.status_code == 422
