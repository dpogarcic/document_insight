"""FastAPI dependency composition for application services."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.api.errors import raise_api_error
from document_insight.application.auth.models import AuthorizationContext
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
from document_insight.infrastructure.database.session import get_db_session
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
from document_insight.infrastructure.user.repository import SqlAlchemyUserRepository
from document_insight.infrastructure.user_department.repository import (
    SqlAlchemyUserDepartmentRepository,
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
]


@lru_cache
def get_password_hasher() -> Argon2PasswordHasher:
    """Create the process-wide password hashing adapter and timing hash."""
    return Argon2PasswordHasher()


def get_auth_service(
    session: DatabaseSession,
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


def get_current_user(
    credentials: BearerCredentials,
    settings: ApplicationSettings,
) -> AuthorizationContext:
    """Authenticate a bearer token and return trusted authorization claims."""
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
        return authenticator.authenticate(credentials.credentials)
    except jwt.InvalidTokenError:
        raise_api_error(
            401,
            "invalid_access_token",
            "A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
    session: DatabaseSession,
    settings: ApplicationSettings,
    object_storage: ObjectStorage,
    processing_queue: ProcessingQueue,
) -> IngestionService:
    """Compose the storage-stage ingestion workflow for one request."""
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


def get_job_service(session: DatabaseSession) -> JobService:
    """Compose the authorized processing-job query service for one request."""
    return JobService(
        jobs=SqlAlchemyJobRepository(session),
        document_versions=SqlAlchemyDocumentVersionRepository(session),
        document_departments=SqlAlchemyDocumentDepartmentRepository(session),
    )


def get_document_library_service(session: DatabaseSession) -> DocumentLibraryService:
    """Compose the authorization-safe document-library query service."""
    return DocumentLibraryService(
        documents=SqlAlchemyDocumentRepository(session),
        departments=SqlAlchemyDepartmentRepository(session),
        document_departments=SqlAlchemyDocumentDepartmentRepository(session),
        document_versions=SqlAlchemyDocumentVersionRepository(session),
        transactions=SqlAlchemyTransactionManager(session),
    )


def get_query_preparation_service(
    session: DatabaseSession, settings: ApplicationSettings
) -> QueryPreparationService:
    """Compose the complete profile-bound, authorization-safe RAG workflow."""
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
