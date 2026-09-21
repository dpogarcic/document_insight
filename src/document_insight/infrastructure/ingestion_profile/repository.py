"""SQLAlchemy repository for immutable ingestion-profile reads."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.ingestion_profile.model import IngestionProfileModel
from document_insight.infrastructure.ingestion_profile.protocol import (
    IngestionProfile,
    IngestionProfileRepository,
)


class SqlAlchemyIngestionProfileRepository(IngestionProfileRepository):
    """Read an ingestion bundle without resolving child profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: UUID) -> IngestionProfile | None:
        """Load one immutable ingestion profile."""
        model = await self._session.scalar(
            select(IngestionProfileModel).where(IngestionProfileModel.id == profile_id)
        )
        if model is None:
            return None
        return IngestionProfile(
            ingestion_profile_id=model.id,
            ner_profile_id=model.ner_profile_id,
            chunking_profile_id=model.chunking_profile_id,
            lexical_profile_id=model.lexical_profile_id,
            embedding_profile_id=model.embedding_profile_id,
        )
