"""Regression tests for authorized vector retrieval SQL bindings."""

import asyncio
from uuid import UUID

from sqlalchemy.dialects.postgresql.asyncpg import dialect
from sqlalchemy.sql.sqltypes import Float

from document_insight.infrastructure.retrieval.protocol import RetrievalScope
from document_insight.infrastructure.retrieval.repository import (
    SqlAlchemyAuthorizedRetrievalRepository,
)


class _Session:
    """Capture a statement without executing it against PostgreSQL."""

    def __init__(self) -> None:
        self.statement: object | None = None

    async def execute(self, statement: object) -> tuple[object, ...]:
        self.statement = statement
        return ()


def test_vector_search_binds_similarity_constant_as_numeric() -> None:
    """The scalar used to map distance to similarity must not be serialized as a vector."""
    session = _Session()
    repository = SqlAlchemyAuthorizedRetrievalRepository(session)  # type: ignore[arg-type]

    result = asyncio.run(
        repository.vector_search(
            RetrievalScope(
                UUID("00000000-0000-0000-0000-000000000001"),
                (UUID("00000000-0000-0000-0000-000000000002"),),
            ),
            UUID("00000000-0000-0000-0000-000000000003"),
            (0.1, 0.2, 0.3),
            5,
        )
    )

    assert result == ()
    assert session.statement is not None
    compiled = session.statement.compile(dialect=dialect())  # type: ignore[union-attr]
    scalar_binds = [bind for bind in compiled.binds.values() if bind.value == 1.0]
    assert len(scalar_binds) == 2
    assert all(isinstance(bind.type, Float) for bind in scalar_binds)
