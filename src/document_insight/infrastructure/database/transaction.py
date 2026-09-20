"""SQLAlchemy transaction boundary shared by entity repositories."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class TransactionManager(Protocol):
    """Provide an atomic boundary across multiple entity repositories."""

    def begin(self) -> AbstractAsyncContextManager[None]:
        """Open one transaction for coordinated repository operations."""


class SqlAlchemyTransactionManager(TransactionManager):
    """Coordinate repository writes on one request-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def begin(self) -> AbstractAsyncContextManager[None]:
        """Return a transaction context matching the protocol exactly."""
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Commit coordinated writes or roll them all back."""
        async with self._session.begin():
            yield
