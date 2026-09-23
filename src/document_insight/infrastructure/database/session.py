"""Asynchronous database engine and request-scoped session management."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Literal
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import SessionTransaction

from document_insight.config import get_settings

DatabaseRole = Literal[
    "read", "write", "auth", "worker", "reconciler", "monitor", "profile_operator"
]


def _database_url(role: DatabaseRole) -> str:
    """Require a dedicated PostgreSQL credential for each runtime capability."""
    settings = get_settings()
    url = {
        "read": settings.database_read_url,
        "write": settings.database_write_url,
        "auth": settings.database_auth_url,
        "worker": settings.database_worker_url,
        "reconciler": settings.database_reconciler_url,
        "monitor": settings.database_monitor_url,
        "profile_operator": settings.database_profile_operator_url,
    }[role]
    if url is not None:
        return url
    if settings.database_url.startswith("sqlite"):
        return settings.database_url
    raise RuntimeError(f"DATABASE_{role.upper()}_URL must be configured")


@event.listens_for(Session, "after_begin")
def _set_transaction_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Bind verified actor or durable job identity to every PostgreSQL transaction."""
    if connection.dialect.name != "postgresql" or transaction.nested:
        return
    actor_id = session.info.get("rls_actor_id")
    job_id = session.info.get("rls_job_id")
    if isinstance(actor_id, UUID):
        connection.execute(
            text("SELECT set_config('app.user_id', :actor_id, true)"),
            {"actor_id": str(actor_id)},
        )
    if isinstance(job_id, UUID):
        connection.execute(
            text("SELECT set_config('app.job_id', :job_id, true)"),
            {"job_id": str(job_id)},
        )


def _postgres_engine_kwargs() -> dict[str, object]:
    """Bound application checkouts while PgBouncer bounds server connections.

    Disable asyncpg's own statement cache. SQLAlchemy has a separate prepared
    statement cache; the pinned PgBouncer 1.24 deployment enables
    protocol-level prepared statement tracking by default for transaction pooling.
    """
    settings = get_settings()
    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        # Fail fast under saturation. SQLAlchemy's own default (30s) would make
        # every caller wait nearly half a minute for the same safe 503 a short
        # timeout returns immediately; a stuck request is not more available.
        "pool_timeout": settings.database_pool_timeout_seconds,
        "connect_args": {"statement_cache_size": 0},
    }


@lru_cache
def get_engine(role: DatabaseRole = "read") -> AsyncEngine:
    """Create one process-wide async engine per restricted database role."""
    url = _database_url(role)
    extra = _postgres_engine_kwargs() if url.startswith("postgresql") else {}
    return create_async_engine(url, pool_pre_ping=True, **extra)


@lru_cache
def get_session_factory(role: DatabaseRole = "read") -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to one restricted database role."""
    return async_sessionmaker(get_engine(role), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a read-only session for a request."""
    async with get_session_factory("read")() as session:
        yield session


async def get_write_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an API-write session for ingestion and activation."""
    async with get_session_factory("write")() as session:
        yield session


async def get_auth_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a narrowly privileged bootstrap and login session."""
    async with get_session_factory("auth")() as session:
        yield session
