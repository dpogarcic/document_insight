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

    async def list_all(self) -> tuple[IngestionProfile, ...]:
        """List bundle identities without loading member entities."""
        models = await self._session.scalars(
            select(IngestionProfileModel).order_by(IngestionProfileModel.created_at.desc())
        )
        return tuple(
            IngestionProfile(
                model.id,
                model.ner_profile_id,
                model.chunking_profile_id,
                model.lexical_profile_id,
                model.embedding_profile_id,
            )
            for model in models
        )

    async def create(self, profile: IngestionProfile) -> None:
        """Add an immutable ingestion bundle."""
        self._session.add(
            IngestionProfileModel(
                id=profile.ingestion_profile_id,
                ner_profile_id=profile.ner_profile_id,
                chunking_profile_id=profile.chunking_profile_id,
                lexical_profile_id=profile.lexical_profile_id,
                embedding_profile_id=profile.embedding_profile_id,
            )
        )
