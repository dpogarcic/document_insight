"""SQLAlchemy read adapter for immutable query profile bundles."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.query_profile.model import (
    QueryProfileEmbeddingCohortModel,
    QueryProfileLexicalCohortModel,
    QueryProfileModel,
)
from document_insight.infrastructure.query_profile.protocol import (
    QueryProfileRepository,
    ResolvedQueryProfile,
)


class SqlAlchemyQueryProfileRepository(QueryProfileRepository):
    """Read one immutable query bundle and its approved retrieval cohorts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, query_profile_id: UUID) -> ResolvedQueryProfile | None:
        """Return a query profile only when its immutable parent exists."""
        model = await self._session.scalar(
            select(QueryProfileModel).where(QueryProfileModel.id == query_profile_id)
        )
        if model is None:
            return None
        lexical_profile_ids = tuple(
            await self._session.scalars(
                select(QueryProfileLexicalCohortModel.lexical_profile_id).where(
                    QueryProfileLexicalCohortModel.query_profile_id == query_profile_id
                )
            )
        )
        embedding_profile_ids = tuple(
            await self._session.scalars(
                select(QueryProfileEmbeddingCohortModel.embedding_profile_id).where(
                    QueryProfileEmbeddingCohortModel.query_profile_id == query_profile_id
                )
            )
        )
        return ResolvedQueryProfile(
            query_profile_id,
            lexical_profile_ids,
            embedding_profile_ids,
            model.reranker_profile_id,
            model.generation_profile_id,
            model.retrieval_snapshot_id,
        )
