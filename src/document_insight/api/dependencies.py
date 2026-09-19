"""FastAPI dependency composition for application services."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.api.errors import raise_api_error
from document_insight.application.auth.service import AuthService
from document_insight.application.ingestion.service import IngestionService
from document_insight.config import Settings, get_settings
from document_insight.domain.auth import AuthenticatedUser
from document_insight.infrastructure.database.auth_repository import SqlAlchemyAuthRepository
from document_insight.infrastructure.database.document_repository import (
    SqlAlchemyDocumentRepository,
)
from document_insight.infrastructure.database.session import get_db_session
from document_insight.infrastructure.object_storage import S3OriginalObjectStorage
from document_insight.infrastructure.security import (
    Argon2PasswordHasher,
    JwtTokenAuthenticator,
    JwtTokenIssuer,
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
    repository = SqlAlchemyAuthRepository(session)
    token_issuer = JwtTokenIssuer(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.jwt_access_token_expire_minutes,
    )
    return AuthService(repository, get_password_hasher(), token_issuer)


def get_current_user(
    credentials: BearerCredentials,
    settings: ApplicationSettings,
) -> AuthenticatedUser:
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


def get_ingestion_service(
    session: DatabaseSession,
    settings: ApplicationSettings,
    object_storage: ObjectStorage,
) -> IngestionService:
    """Compose the storage-stage ingestion workflow for one request."""
    return IngestionService(
        repository=SqlAlchemyDocumentRepository(session),
        object_storage=object_storage,
        max_upload_bytes=settings.upload_max_bytes,
    )
