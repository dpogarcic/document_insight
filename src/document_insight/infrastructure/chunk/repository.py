"""SQLAlchemy repository for version-scoped chunks."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.chunk.model import ChunkModel
from document_insight.infrastructure.chunk.protocol import (
    ChunkForEmbedding,
    ChunkRepository,
    CreateChunks,
)


class SqlAlchemyChunkRepository(ChunkRepository):
    """Own immutable chunk persistence and generated lexical-index rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, command: CreateChunks) -> None:
        """Persist a complete deterministic chunk set for one document version."""
        self._session.add_all(
            ChunkModel(
                tenant_id=command.tenant_id,
                document_version_id=command.document_version_id,
                index_generation_id=command.index_generation_id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                page_number=chunk.page_number,
                language=command.language,
            )
            for chunk in command.chunks
        )

    async def list_for_embedding(
        self, index_generation_id: UUID, tenant_id: UUID
    ) -> tuple[ChunkForEmbedding, ...]:
        """Read one generation's chunks in stable order."""
        rows = await self._session.execute(
            select(ChunkModel.id, ChunkModel.text)
            .where(
                ChunkModel.index_generation_id == index_generation_id,
                ChunkModel.tenant_id == tenant_id,
            )
            .order_by(ChunkModel.ordinal)
        )
        return tuple(ChunkForEmbedding(chunk_id=row.id, text=row.text) for row in rows)
