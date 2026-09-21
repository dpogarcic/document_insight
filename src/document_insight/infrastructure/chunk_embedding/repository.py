"""PostgreSQL persistence for profile-scoped chunk embeddings."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.chunk_embedding.model import ChunkEmbeddingModel
from document_insight.infrastructure.chunk_embedding.protocol import (
    ChunkEmbeddingRepository,
    CreateChunkEmbeddings,
)


class SqlAlchemyChunkEmbeddingRepository(ChunkEmbeddingRepository):
    """Own idempotent vectors for one chunk/profile pairing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, command: CreateChunkEmbeddings) -> None:
        """Insert only vectors absent from a prior worker attempt."""
        if not command.embeddings:
            return
        statement = insert(ChunkEmbeddingModel).values(
            [
                {
                    "chunk_id": embedding.chunk_id,
                    "embedding_profile_id": command.embedding_profile_id,
                    "embedding": embedding.values,
                }
                for embedding in command.embeddings
            ]
        )
        await self._session.execute(
            statement.on_conflict_do_nothing(index_elements=["chunk_id", "embedding_profile_id"])
        )
