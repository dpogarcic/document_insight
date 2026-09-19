"""FastAPI dependency composition for application services."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.auth.service import AuthService
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.database.auth_repository import SqlAlchemyAuthRepository
from document_insight.infrastructure.database.session import get_db_session
from document_insight.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


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
