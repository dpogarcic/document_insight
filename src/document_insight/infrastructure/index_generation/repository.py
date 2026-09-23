"""SQLAlchemy repository for version-scoped index generations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.index_generation.model import IndexGenerationModel
from document_insight.infrastructure.index_generation.protocol import (
    CreateIndexGeneration,
    IndexGeneration,
    IndexGenerationRepository,
)


class SqlAlchemyIndexGenerationRepository(IndexGenerationRepository):
    """Own immutable profile binding and stage state for one generation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, command: CreateIndexGeneration) -> None:
        """Persist a building generation with its resolved ingestion profile."""
        self._session.add(
            IndexGenerationModel(
                id=command.index_generation_id,
                tenant_id=command.tenant_id,
                document_version_id=command.document_version_id,
                ingestion_profile_id=command.ingestion_profile_id,
                status="building",
            )
        )

    async def get(self, index_generation_id: UUID, tenant_id: UUID) -> IndexGeneration | None:
        """Load worker-required generation state without related records."""
        model = await self._session.scalar(
            select(IndexGenerationModel).where(
                IndexGenerationModel.id == index_generation_id,
                IndexGenerationModel.tenant_id == tenant_id,
            )
        )
        if model is None:
            return None
        return IndexGeneration(
            index_generation_id=model.id,
            ingestion_profile_id=model.ingestion_profile_id,
            chunking_completed_at=model.chunking_completed_at,
            embedding_completed_at=model.embedding_completed_at,
        )

    async def mark_chunking_complete(
        self, index_generation_id: UUID, completed_at: datetime
    ) -> None:
        """Record the generated FTS index together with its chunks."""
        await self._session.execute(
            update(IndexGenerationModel)
            .where(IndexGenerationModel.id == index_generation_id)
            .values(chunking_completed_at=completed_at, lexical_indexed_at=completed_at)
        )

    async def mark_embedding_complete(
        self, index_generation_id: UUID, completed_at: datetime
    ) -> None:
        """Record that all generation chunks have their profile-bound vectors."""
        await self._session.execute(
            update(IndexGenerationModel)
            .where(IndexGenerationModel.id == index_generation_id)
            .values(embedding_completed_at=completed_at)
        )

    async def mark_ready(self, index_generation_id: UUID) -> None:
        """Persist the terminal ready state after chunk and embedding checkpoints."""
        await self._session.execute(
            update(IndexGenerationModel)
            .where(IndexGenerationModel.id == index_generation_id)
            .values(status="ready")
        )

    async def referenced_ingestion_profile_ids(self) -> tuple[UUID, ...]:
        """List distinct ready generation profiles, including older document versions."""
        return tuple(
            await self._session.scalars(
                select(IndexGenerationModel.ingestion_profile_id)
                .where(IndexGenerationModel.status == "ready")
                .distinct()
            )
        )
