"""Authenticated end-to-end scenario: ingest, wait, activate, and query.

Exercises the real Docker Compose service boundaries this project requires for its
end-to-end tier (docs/CODE_QUALITY.md): PostgreSQL through the same RLS-restricted
login roles production uses, and Redis/RQ through a real enqueue and a real worker
drain of the durable ingestion job. PDF parsing and page-window chunking run for
real too.

Per CODE_QUALITY.md's testing standard ("no real model providers ... network calls"),
NER, embedding, reranking, and generation use protocol-conformant fakes instead of the
real spaCy/Mistral adapters — those adapters are unit-tested separately. Object storage
also uses the in-memory fake already established by tests/api/test_ingest.py, since
Compose does not publish the object-storage (MinIO) service on the host for a
standalone test run; only the disposable database-test and redis-test services are.

Covers docs/ARCHITECTURE.md's required scenario: an authenticated upload, successful
background processing, an authorized query with cited sources, and a denied-department
query — plus the "ready but not current" invariant (a processed version stays
unsearchable until a tenant admin explicitly activates it).
"""

import asyncio
import signal
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from math import sqrt
from random import Random
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis import Redis as SyncRedis
from rq import SimpleWorker
from sqlalchemy import delete
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import document_insight.worker.ingestion as worker_ingestion_module
from document_insight.api.app import create_app
from document_insight.api.dependencies import (
    CurrentUser,
    DatabaseSession,
    get_db_session,
    get_object_storage,
    get_query_preparation_service,
    get_query_rate_limiter,
)
from document_insight.application.auth.models import UserCredentials, UserRole
from document_insight.application.configuration.models import (
    EmbeddingConfiguration,
    GenerationConfiguration,
    NerConfiguration,
    RerankingConfiguration,
)
from document_insight.application.processing.models import (
    DocumentLanguage,
    EntityLabel,
    NamedEntity,
    NerResult,
)
from document_insight.application.query.profile_resolver import QueryProfileResolver
from document_insight.application.query.service import QueryPreparationService
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.session import (
    get_auth_db_session,
    get_write_db_session,
)
from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.department.repository import SqlAlchemyDepartmentRepository
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.embedding.protocol import TextEmbedder, TextEmbedderFactory
from document_insight.infrastructure.generation.protocol import (
    GroundedAnswer,
    GroundedAnswerGenerator,
    GroundedAnswerGeneratorFactory,
    GroundingPassage,
)
from document_insight.infrastructure.ner.protocol import (
    NamedEntityRecognizer,
    NamedEntityRecognizerFactory,
)
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)
from document_insight.infrastructure.reranker.protocol import (
    Reranker,
    RerankerFactory,
    RerankInput,
    RerankScore,
)
from document_insight.infrastructure.retrieval.repository import (
    SqlAlchemyAuthorizedRetrievalRepository,
)
from document_insight.infrastructure.security.query_rate_limiter import RateLimitDecision
from document_insight.infrastructure.security.token_issuer import JwtTokenIssuer
from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user_department.model import UserDepartmentModel

_JWT_SECRET = SecretStr("e2e-ingest-to-query-secret-key-not-for-production")
_FAKE_ENTITY = NamedEntity("Acme Corp", "acme corp", EntityLabel.ORG)
_DOCUMENT_TEXT = (
    "Employees receive twenty five paid vacation days each calendar year.",
    "Acme Corp Human Resources Policy",
)


# --- Protocol-conformant fakes for the vendor-model boundary ---------------------


def _unit_vector(seed: str, dimensions: int) -> tuple[float, ...]:
    """Deterministic pseudo-embedding; the fake reranker decides citations, not distance."""
    rng = Random(seed)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(dimensions)]
    magnitude = sqrt(sum(value * value for value in raw)) or 1.0
    return tuple(value / magnitude for value in raw)


class FakeTextEmbedder(TextEmbedder):
    async def embed(
        self, texts: tuple[str, ...], configuration: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        return tuple(_unit_vector(text, configuration.dimensions) for text in texts)


class FakeTextEmbedderFactory(TextEmbedderFactory):
    def create(self, configuration: EmbeddingConfiguration) -> TextEmbedder:
        return FakeTextEmbedder()


class FakeReranker(Reranker):
    async def rerank(
        self,
        question: str,
        candidates: tuple[RerankInput, ...],
        configuration: RerankingConfiguration,
    ) -> tuple[RerankScore, ...]:
        return tuple(RerankScore(candidate.chunk_id, 0.9) for candidate in candidates)


class FakeRerankerFactory(RerankerFactory):
    def create(self, configuration: RerankingConfiguration) -> Reranker:
        return FakeReranker()


class FakeGroundedAnswerGenerator(GroundedAnswerGenerator):
    async def generate(
        self,
        question: str,
        passages: tuple[GroundingPassage, ...],
        configuration: GenerationConfiguration,
    ) -> GroundedAnswer:
        quoted = " ".join(passage.text for passage in passages)
        return GroundedAnswer(
            f"Based on the authorized evidence: {quoted}",
            tuple(passage.chunk_id for passage in passages),
        )


class FakeGroundedAnswerGeneratorFactory(GroundedAnswerGeneratorFactory):
    def create(self, configuration: GenerationConfiguration) -> GroundedAnswerGenerator:
        return FakeGroundedAnswerGenerator()


class FakeNamedEntityRecognizer(NamedEntityRecognizer):
    def recognize(self, text: str) -> NerResult:
        return NerResult(
            language=DocumentLanguage.ENGLISH,
            provider_name="fake",
            model_name="fake-ner-v1",
            entities=(_FAKE_ENTITY,),
        )


class FakeNamedEntityRecognizerFactory(NamedEntityRecognizerFactory):
    def create(self, configuration: NerConfiguration) -> NamedEntityRecognizer:
        return FakeNamedEntityRecognizer()


class FakeAllowAllRateLimiter:
    """Skip real Redis rate limiting; the ingestion queue already covers Redis/RQ."""

    async def acquire(
        self, tenant_id: UUID, user_id: UUID, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        return RateLimitDecision(True, window_seconds)


@dataclass
class FakeObjectStorage:
    """Shared in-memory original-file store used by both the API and the worker."""

    objects: dict[str, bytes] = field(default_factory=dict)

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def get(self, key: str) -> bytes:
        return self.objects[key]


# --- A hand-built minimal PDF, since generating one is otherwise out of scope ------


def _build_pdf(lines: tuple[str, ...]) -> bytes:
    """Build a byte-exact minimal single-page PDF with real extractable text."""
    content = "\n".join(
        f"BT /F1 14 Tf 72 {720 - 20 * index} Td ({line}) Tj ET" for index, line in enumerate(lines)
    )
    stream = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return bytes(out)


# --- Disposable Docker Compose infrastructure -------------------------------------


class _E2ESettings(BaseSettings):
    """Load only the disposable Compose credentials this scenario needs."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None
    database_read_password: SecretStr | None = None
    database_write_password: SecretStr | None = None
    database_auth_password: SecretStr | None = None
    database_worker_password: SecretStr | None = None
    test_redis_url: str | None = None


def _load_settings() -> _E2ESettings:
    """Require every disposable credential, or skip with a precise reason."""
    settings = _E2ESettings()
    missing = [
        name
        for name, value in (
            ("TEST_DATABASE_RUNTIME_URL", settings.test_database_runtime_url),
            ("TEST_DATABASE_OWNER_PASSWORD", settings.test_database_owner_password),
            ("DATABASE_READ_PASSWORD", settings.database_read_password),
            ("DATABASE_WRITE_PASSWORD", settings.database_write_password),
            ("DATABASE_AUTH_PASSWORD", settings.database_auth_password),
            ("DATABASE_WORKER_PASSWORD", settings.database_worker_password),
            ("TEST_REDIS_URL", settings.test_redis_url),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"{', '.join(missing)} required for the ingest-to-query end-to-end test")
    return settings


def _role_url(runtime_url: URL, username: str, password: SecretStr) -> URL:
    """Derive one restricted-role connection URL without ever printing a secret."""
    return runtime_url.set(username=username, password=password.get_secret_value())


@dataclass(frozen=True)
class _Tenancy:
    """Identifiers for one seeded tenant with two departments and three users."""

    tenant_id: UUID
    legal_department_id: UUID
    general_department_id: UUID
    admin_token: str
    legal_viewer_token: str
    general_viewer_token: str


@dataclass(frozen=True)
class E2EContext:
    """Everything one HTTP-driven scenario needs against the disposable stack."""

    client: AsyncClient
    tenancy: _Tenancy
    queue_name: str
    redis_url: str
    storage: FakeObjectStorage
    worker_session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def anyio_backend() -> str:
    """Run the async end-to-end scenario on asyncio."""
    return "asyncio"


async def _seed_tenancy(owner_engine, tenant_settings: Settings) -> _Tenancy:
    """Create one tenant, two departments, and three users through the table owner."""
    tenant_id, legal_department_id, general_department_id = uuid4(), uuid4(), uuid4()
    admin_id, legal_viewer_id, general_viewer_id = uuid4(), uuid4(), uuid4()
    async with owner_engine.begin() as connection:
        await connection.execute(
            TenantModel.__table__.insert(),
            [{"id": tenant_id, "name": f"E2E Tenant {tenant_id}"}],
        )
        await connection.execute(
            DepartmentModel.__table__.insert(),
            [
                {"id": legal_department_id, "tenant_id": tenant_id, "name": "Legal"},
                {"id": general_department_id, "tenant_id": tenant_id, "name": "General"},
            ],
        )
        await connection.execute(
            UserModel.__table__.insert(),
            [
                {
                    "id": admin_id,
                    "tenant_id": tenant_id,
                    "email": f"admin-{admin_id}@example.test",
                    "display_name": "E2E Admin",
                    "password_hash": "unused-in-e2e-test",
                    "role": UserRole.TENANT_ADMIN.value,
                },
                {
                    "id": legal_viewer_id,
                    "tenant_id": tenant_id,
                    "email": f"legal-{legal_viewer_id}@example.test",
                    "display_name": "Legal Viewer",
                    "password_hash": "unused-in-e2e-test",
                    "role": UserRole.VIEWER.value,
                },
                {
                    "id": general_viewer_id,
                    "tenant_id": tenant_id,
                    "email": f"general-{general_viewer_id}@example.test",
                    "display_name": "General Viewer",
                    "password_hash": "unused-in-e2e-test",
                    "role": UserRole.VIEWER.value,
                },
            ],
        )
        await connection.execute(
            UserDepartmentModel.__table__.insert(),
            [
                {
                    "user_id": admin_id,
                    "department_id": general_department_id,
                    "tenant_id": tenant_id,
                },
                {
                    "user_id": legal_viewer_id,
                    "department_id": legal_department_id,
                    "tenant_id": tenant_id,
                },
                {
                    "user_id": general_viewer_id,
                    "department_id": general_department_id,
                    "tenant_id": tenant_id,
                },
            ],
        )
    issuer = JwtTokenIssuer(
        secret_key=tenant_settings.jwt_secret_key,
        algorithm=tenant_settings.jwt_algorithm,
        issuer=tenant_settings.jwt_issuer,
        audience=tenant_settings.jwt_audience,
        expire_minutes=tenant_settings.jwt_access_token_expire_minutes,
    )

    def _token(user_id: UUID, role: UserRole, department_id: UUID, email: str) -> str:
        return issuer.issue(
            UserCredentials(
                user_id=user_id,
                tenant_id=tenant_id,
                department_ids=(department_id,),
                email=email,
                display_name=role.value,
                role=role,
                password_hash="unused-in-e2e-test",
            )
        ).value

    return _Tenancy(
        tenant_id=tenant_id,
        legal_department_id=legal_department_id,
        general_department_id=general_department_id,
        admin_token=_token(
            admin_id, UserRole.TENANT_ADMIN, general_department_id, f"admin-{admin_id}@example.test"
        ),
        legal_viewer_token=_token(
            legal_viewer_id,
            UserRole.VIEWER,
            legal_department_id,
            f"legal-{legal_viewer_id}@example.test",
        ),
        general_viewer_token=_token(
            general_viewer_id,
            UserRole.VIEWER,
            general_department_id,
            f"general-{general_viewer_id}@example.test",
        ),
    )


def _query_preparation_override(
    session: DatabaseSession, actor: CurrentUser
) -> QueryPreparationService:
    """Rebuild the production query pipeline with fakes only at the model-provider edge."""
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
        embedders=FakeTextEmbedderFactory(),
        rerankers=FakeRerankerFactory(),
        generators=FakeGroundedAnswerGeneratorFactory(),
        release_database_session=session.close,
    )


@pytest.fixture
async def e2e_context() -> AsyncIterator[E2EContext]:
    """Wire the real FastAPI app to the disposable Postgres and Redis Compose services."""
    settings = _load_settings()
    assert settings.test_database_runtime_url is not None
    runtime_url = make_url(settings.test_database_runtime_url)
    owner_url = runtime_url.set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    read_url = _role_url(runtime_url, "di_api_read_login", settings.database_read_password)
    write_url = _role_url(runtime_url, "di_api_write_login", settings.database_write_password)
    auth_url = _role_url(runtime_url, "di_auth_login", settings.database_auth_password)
    worker_url = _role_url(runtime_url, "di_worker_login", settings.database_worker_password)

    owner_engine = create_async_engine(owner_url)
    read_engine = create_async_engine(read_url)
    write_engine = create_async_engine(write_url)
    auth_engine = create_async_engine(auth_url)
    worker_engine = create_async_engine(worker_url)
    read_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    write_factory = async_sessionmaker(write_engine, expire_on_commit=False)
    auth_factory = async_sessionmaker(auth_engine, expire_on_commit=False)
    worker_session_factory = async_sessionmaker(worker_engine, expire_on_commit=False)

    queue_name = f"e2e-ingestion-{uuid4().hex}"
    assert settings.test_redis_url is not None
    app_settings = Settings(
        jwt_secret_key=_JWT_SECRET,
        redis_url=settings.test_redis_url,
        rq_ingestion_queue_name=queue_name,
    )
    tenancy = await _seed_tenancy(owner_engine, app_settings)
    storage = FakeObjectStorage()

    application = create_app()

    async def _override_read() -> AsyncIterator[AsyncSession]:
        async with read_factory() as session:
            yield session

    async def _override_write() -> AsyncIterator[AsyncSession]:
        async with write_factory() as session:
            yield session

    async def _override_auth() -> AsyncIterator[AsyncSession]:
        async with auth_factory() as session:
            yield session

    application.dependency_overrides[get_settings] = lambda: app_settings
    application.dependency_overrides[get_db_session] = _override_read
    application.dependency_overrides[get_write_db_session] = _override_write
    application.dependency_overrides[get_auth_db_session] = _override_auth
    application.dependency_overrides[get_object_storage] = lambda: storage
    application.dependency_overrides[get_query_rate_limiter] = lambda: FakeAllowAllRateLimiter()
    application.dependency_overrides[get_query_preparation_service] = _query_preparation_override

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            yield E2EContext(
                client=client,
                tenancy=tenancy,
                queue_name=queue_name,
                redis_url=settings.test_redis_url,
                storage=storage,
                worker_session_factory=worker_session_factory,
            )
        finally:
            async with owner_engine.begin() as connection:
                # Documents and users must be gone before departments: both
                # document_departments and user_departments restrict deleting a
                # department still referenced by an assignment or a membership.
                await connection.execute(
                    delete(DocumentModel).where(DocumentModel.tenant_id == tenancy.tenant_id)
                )
                await connection.execute(
                    delete(UserModel).where(UserModel.tenant_id == tenancy.tenant_id)
                )
                await connection.execute(
                    delete(TenantModel).where(TenantModel.id == tenancy.tenant_id)
                )
    for engine in (owner_engine, read_engine, write_engine, auth_engine, worker_engine):
        await engine.dispose()


async def _drain_ingestion_queue(monkeypatch: pytest.MonkeyPatch, context: E2EContext) -> None:
    """Run the real worker entry point with only the model-provider edge faked."""
    worker_settings = Settings(
        jwt_secret_key=_JWT_SECRET,
        mistral_api_key=SecretStr("unused-fake-provider"),
        redis_url=context.redis_url,
        rq_ingestion_queue_name=context.queue_name,
    )
    monkeypatch.setattr(worker_ingestion_module, "get_settings", lambda: worker_settings)
    monkeypatch.setattr(
        worker_ingestion_module,
        "get_session_factory",
        lambda role: context.worker_session_factory,
    )
    monkeypatch.setattr(
        worker_ingestion_module, "S3OriginalObjectStorage", lambda *args, **kwargs: context.storage
    )
    monkeypatch.setattr(
        worker_ingestion_module,
        "MistralTextEmbedderFactory",
        lambda *args, **kwargs: FakeTextEmbedderFactory(),
    )
    monkeypatch.setattr(
        worker_ingestion_module,
        "SpacyNamedEntityRecognizerFactory",
        lambda: FakeNamedEntityRecognizerFactory(),
    )
    # RQ's worker loop installs OS signal handlers, which only the main thread may
    # do; this burst drain runs on a worker thread so asyncio.run() inside the real
    # process_ingestion_job entry point does not collide with this test's own loop.
    monkeypatch.setattr(signal, "signal", lambda *args, **kwargs: None)

    def _run_burst_worker() -> None:
        connection = SyncRedis.from_url(context.redis_url)
        try:
            SimpleWorker([context.queue_name], connection=connection).work(burst=True)
        finally:
            connection.close()

    await asyncio.to_thread(_run_burst_worker)


async def _wait_until_processed(
    client: AsyncClient, job_id: str, headers: dict[str, str]
) -> dict[str, object]:
    """Poll the durable job record until it reaches a terminal status."""
    for _ in range(20):
        response = await client.get(f"/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"ready", "failed", "cancelled"}:
            return body
        await asyncio.sleep(0.25)
    pytest.fail(f"Job {job_id} never reached a terminal status")


@pytest.mark.anyio
async def test_authenticated_ingest_to_query_end_to_end(
    e2e_context: E2EContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest, wait for real background processing, activate, then query with citations.

    Also covers the required denied-department case: a viewer outside the document's
    department receives the safe "no evidence" answer rather than the cited passage.
    """
    client = e2e_context.client
    tenancy = e2e_context.tenancy
    admin_headers = {"Authorization": f"Bearer {tenancy.admin_token}"}
    legal_headers = {"Authorization": f"Bearer {tenancy.legal_viewer_token}"}
    general_headers = {"Authorization": f"Bearer {tenancy.general_viewer_token}"}
    pdf_bytes = _build_pdf(_DOCUMENT_TEXT)

    ingested = await client.post(
        "/ingest",
        headers=admin_headers,
        data={"department_ids": str(tenancy.legal_department_id)},
        files={"file": ("hr-policy.pdf", pdf_bytes, "application/pdf")},
    )
    assert ingested.status_code == 202
    body = ingested.json()
    assert body["job_status"] == "queued"
    document_id = body["document_id"]
    version_id = body["document_version_id"]
    job_id = body["job_id"]

    queued_job = await client.get(f"/jobs/{job_id}", headers=admin_headers)
    assert queued_job.json()["status"] == "queued"

    # A real RQ worker dequeues and runs the actual processing pipeline; only the
    # spaCy/Mistral model-provider edge is faked (see module docstring).
    await _drain_ingestion_queue(monkeypatch, e2e_context)
    finished_job = await _wait_until_processed(client, job_id, admin_headers)
    assert finished_job["status"] == "ready"
    assert finished_job["error_code"] is None

    # A ready version is not yet the searchable current version.
    pre_activation = await client.post(
        "/query",
        headers=legal_headers,
        json={"question": "How many paid vacation days do employees receive?"},
    )
    assert pre_activation.status_code == 200
    assert pre_activation.json()["confidence"] == 0.0
    assert pre_activation.json()["sources"] == []

    activation = await client.post(
        f"/documents/{document_id}/activate",
        headers=admin_headers,
        json={"document_version_id": version_id},
    )
    assert activation.status_code == 200
    assert activation.json() == {
        "document_id": document_id,
        "current_ready_version_id": version_id,
    }

    authorized = await client.post(
        "/query",
        headers=legal_headers,
        json={
            "question": "How many paid vacation days do employees receive?",
            "filter": "Acme",
            "top_k": 3,
        },
    )
    assert authorized.status_code == 200
    result = authorized.json()
    assert result["confidence"] > 0.0
    assert "vacation days" in result["answer"]
    assert len(result["sources"]) == 1
    citation = result["sources"][0]
    assert citation["document_id"] == document_id
    assert citation["document_version_id"] == version_id
    assert citation["page_number"] == 1
    assert "vacation days" in citation["quote"]
    assert result["entities"] == [
        {
            "text": "Acme Corp",
            "label": "ORG",
            "document_version_id": version_id,
        }
    ]

    denied = await client.post(
        "/query",
        headers=general_headers,
        json={"question": "How many paid vacation days do employees receive?"},
    )
    assert denied.status_code == 200
    denied_result = denied.json()
    assert denied_result["confidence"] == 0.0
    assert denied_result["sources"] == []
    assert (
        denied_result["answer"] == "The information is not available in your authorized documents."
    )
