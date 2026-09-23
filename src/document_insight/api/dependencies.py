"""FastAPI dependency composition for application services."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.api.errors import raise_api_error
from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.auth.service import AuthService
from document_insight.application.documents.service import DocumentLibraryService
from document_insight.application.ingestion.service import IngestionService
from document_insight.application.jobs.service import JobService
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
    get_db_session,
    get_write_db_session,
)
from document_insight.infrastructure.database.transaction import (
    SqlAlchemyTransactionManager,
)
from document_insight.infrastructure.department.repository import (
    SqlAlchemyDepartmentRepository,
)
from document_insight.infrastructure.document.repository import SqlAlchemyDocumentRepository
from document_insight.infrastructure.document_department.repository import (
    SqlAlchemyDocumentDepartmentRepository,
)
from document_insight.infrastructure.document_version.repository import (
    SqlAlchemyDocumentVersionRepository,
)
from document_insight.infrastructure.generation.mistral import MistralGroundedAnswerGeneratorFactory
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.job.repository import SqlAlchemyJobRepository
from document_insight.infrastructure.mistral.embedding import MistralTextEmbedderFactory
from document_insight.infrastructure.object_storage.s3 import S3OriginalObjectStorage
from document_insight.infrastructure.observability.query_metrics import PrometheusQueryMetrics
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)
from document_insight.infrastructure.queue.rq import RqProcessingQueue
from document_insight.infrastructure.reranker.mistral import MistralRerankerFactory
from document_insight.infrastructure.retrieval.repository import (
    SqlAlchemyAuthorizedRetrievalRepository,
)
from document_insight.infrastructure.security.password_hasher import Argon2PasswordHasher
from document_insight.infrastructure.security.token_authenticator import JwtTokenAuthenticator
from document_insight.infrastructure.security.token_issuer import JwtTokenIssuer
from document_insight.infrastructure.tenant.repository import SqlAlchemyTenantRepository
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user.repository import SqlAlchemyUserRepository
from document_insight.infrastructure.user_department.model import UserDepartmentModel
from document_insight.infrastructure.user_department.repository import (
    SqlAlchemyUserDepartmentRepository,
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
WriteDatabaseSession = Annotated[AsyncSession, Depends(get_write_db_session)]
AuthDatabaseSession = Annotated[AsyncSession, Depends(get_auth_db_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
]


@lru_cache
def get_password_hasher() -> Argon2PasswordHasher:
    """Create the process-wide password hashing adapter and timing hash."""
    return Argon2PasswordHasher()


def get_auth_service(
    session: AuthDatabaseSession,
    settings: ApplicationSettings,
) -> AuthService:
    """Compose the authentication service for one request."""
    token_issuer = JwtTokenIssuer(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.jwt_access_token_expire_minutes,
    )
    return AuthService(
        tenants=SqlAlchemyTenantRepository(session),
        departments=SqlAlchemyDepartmentRepository(session),
        users=SqlAlchemyUserRepository(session),
        user_departments=SqlAlchemyUserDepartmentRepository(session),
        transactions=SqlAlchemyTransactionManager(session),
        password_hasher=get_password_hasher(),
        token_issuer=token_issuer,
    )


def get_verified_claims(
    credentials: BearerCredentials,
    settings: ApplicationSettings,
) -> AuthorizationContext:
    """Reject invalid credentials before opening any database dependency."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise_api_error(
            401,
            "invalid_access_token",
            "A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    authenticator = JwtTokenAuthenticator(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    try:
        claims = authenticator.authenticate(credentials.credentials)
    except jwt.InvalidTokenError:
        raise_api_error(
            401,
            "invalid_access_token",
            "A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


async def get_current_user(
    claims: Annotated[AuthorizationContext, Depends(get_verified_claims)],
    session: AuthDatabaseSession,
) -> AuthorizationContext:
    """Refresh role and department membership from the system of record."""
    user = await session.scalar(select(UserModel).where(UserModel.id == claims.user_id))
    if user is None or user.tenant_id != claims.tenant_id:
        raise_api_error(
            401,
            "invalid_access_token",
            "A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    departments = tuple(
        await session.scalars(
            select(UserDepartmentModel.department_id)
            .where(
                UserDepartmentModel.user_id == user.id,
                UserDepartmentModel.tenant_id == user.tenant_id,
            )
            .order_by(UserDepartmentModel.department_id)
        )
    )
    if not departments:
        raise_api_error(
            401,
            "invalid_access_token",
            "A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthorizationContext(user.id, user.tenant_id, departments, UserRole(user.role))


CurrentUser = Annotated[AuthorizationContext, Depends(get_current_user)]


def _bind_actor(session: AsyncSession, actor: AuthorizationContext) -> None:
    """Make the verified user available to RLS before the first database statement."""
    session.info["rls_actor_id"] = actor.user_id


def get_object_storage(settings: ApplicationSettings) -> S3OriginalObjectStorage:
    """Create an S3-compatible original-file adapter from validated settings."""
    return S3OriginalObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket_name=settings.s3_bucket_name,
        region=settings.s3_region,
    )


ObjectStorage = Annotated[S3OriginalObjectStorage, Depends(get_object_storage)]


def get_processing_queue(settings: ApplicationSettings) -> RqProcessingQueue:
    """Create the RQ adapter for publishing durable ingestion jobs."""
    return RqProcessingQueue(
        redis_url=settings.redis_url,
        queue_name=settings.rq_ingestion_queue_name,
    )


ProcessingQueue = Annotated[RqProcessingQueue, Depends(get_processing_queue)]


def _mistral_api_key(settings: Settings) -> str:
    """Return the required cloud credential only when an AI capability is composed."""
    if settings.mistral_api_key is None:
        raise RuntimeError("MISTRAL_API_KEY must be configured for AI capabilities")
    return settings.mistral_api_key.get_secret_value()


def get_ingestion_service(
    session: WriteDatabaseSession,
    actor: CurrentUser,
    settings: ApplicationSettings,
    object_storage: ObjectStorage,
    processing_queue: ProcessingQueue,
) -> IngestionService:
    """Compose the storage-stage ingestion workflow for one request."""
    _bind_actor(session, actor)
    return IngestionService(
        documents=SqlAlchemyDocumentRepository(session),
        departments=SqlAlchemyDepartmentRepository(session),
        document_departments=SqlAlchemyDocumentDepartmentRepository(session),
        document_versions=SqlAlchemyDocumentVersionRepository(session),
        jobs=SqlAlchemyJobRepository(session),
        active_profiles=SqlAlchemyActiveProfileRepository(session),
        index_generations=SqlAlchemyIndexGenerationRepository(session),
        transactions=SqlAlchemyTransactionManager(session),
        object_storage=object_storage,
        processing_queue=processing_queue,
        max_upload_bytes=settings.upload_max_bytes,
    )


def get_job_service(session: DatabaseSession, actor: CurrentUser) -> JobService:
    """Compose the authorized processing-job query service for one request."""
    _bind_actor(session, actor)
    return JobService(
        jobs=SqlAlchemyJobRepository(session),
        document_versions=SqlAlchemyDocumentVersionRepository(session),
        document_departments=SqlAlchemyDocumentDepartmentRepository(session),
    )


def _document_library_service(session: AsyncSession) -> DocumentLibraryService:
    """Compose shared document repositories for library reads or activation writes."""
    return DocumentLibraryService(
        documents=SqlAlchemyDocumentRepository(session),
        departments=SqlAlchemyDepartmentRepository(session),
        document_departments=SqlAlchemyDocumentDepartmentRepository(session),
        document_versions=SqlAlchemyDocumentVersionRepository(session),
        transactions=SqlAlchemyTransactionManager(session),
    )


def get_document_library_service(
    session: DatabaseSession, actor: CurrentUser
) -> DocumentLibraryService:
    """Compose a scoped read-only document library service."""
    _bind_actor(session, actor)
    return _document_library_service(session)


def get_document_activation_service(
    session: WriteDatabaseSession, actor: CurrentUser
) -> DocumentLibraryService:
    """Compose a scoped API-write document activation service."""
    _bind_actor(session, actor)
    return _document_library_service(session)


def get_query_preparation_service(
    session: DatabaseSession, settings: ApplicationSettings, actor: CurrentUser
) -> QueryPreparationService:
    """Compose the complete profile-bound, authorization-safe RAG workflow."""
    _bind_actor(session, actor)
    return QueryPreparationService(
        active_profiles=SqlAlchemyActiveProfileRepository(session),
        profile_resolver=QueryProfileResolver(
            SqlAlchemyQueryProfileRepository(session),
            SqlAlchemyCapabilityProfileRepository(session),
            SqlAlchemyConfigurationSnapshotRepository(session),
        ),
        departments=SqlAlchemyDepartmentRepository(session),
        retrieval=SqlAlchemyAuthorizedRetrievalRepository(session),
        embedders=MistralTextEmbedderFactory(
            settings.mistral_base_url,
            _mistral_api_key(settings),
        ),
        rerankers=MistralRerankerFactory(
            settings.mistral_base_url,
            _mistral_api_key(settings),
        ),
        generators=MistralGroundedAnswerGeneratorFactory(
            settings.mistral_base_url,
            _mistral_api_key(settings),
        ),
        metrics=PrometheusQueryMetrics(),
    )
