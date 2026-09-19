"""Asynchronous database engine and request-scoped session management."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from document_insight.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create the process-wide async database engine."""
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create the process-wide request session factory."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one database session for a request and always close it afterward."""
    async with get_session_factory()() as session:
        yield session
