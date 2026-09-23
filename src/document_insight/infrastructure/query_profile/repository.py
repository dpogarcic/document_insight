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

    async def list_all(self) -> tuple[ResolvedQueryProfile, ...]:
        """List bundles and their explicit cohorts."""
        ids = await self._session.scalars(
            select(QueryProfileModel.id).order_by(QueryProfileModel.created_at.desc())
        )
        result: list[ResolvedQueryProfile] = []
        for identifier in ids:
            profile = await self.get(identifier)
            if profile is not None:
                result.append(profile)
        return tuple(result)

    async def create(self, profile: ResolvedQueryProfile) -> None:
        """Add a query bundle and compatible read-cohort associations."""
        self._session.add(
            QueryProfileModel(
                id=profile.query_profile_id,
                reranker_profile_id=profile.reranker_profile_id,
                generation_profile_id=profile.generation_profile_id,
                retrieval_snapshot_id=profile.retrieval_snapshot_id,
            )
        )
        await self._session.flush()
        self._session.add_all(
            QueryProfileLexicalCohortModel(
                query_profile_id=profile.query_profile_id, lexical_profile_id=profile_id
            )
            for profile_id in profile.lexical_profile_ids
        )
        self._session.add_all(
            QueryProfileEmbeddingCohortModel(
                query_profile_id=profile.query_profile_id, embedding_profile_id=profile_id
            )
            for profile_id in profile.embedding_profile_ids
        )
