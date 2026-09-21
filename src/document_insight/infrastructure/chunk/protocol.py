"""Repository contract for version-scoped chunk persistence."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.processing.models import DocumentChunk, DocumentLanguage


@dataclass(frozen=True, slots=True)
class CreateChunks:
    """One deterministic chunking result to persist and lexically index."""

    document_version_id: UUID
    index_generation_id: UUID
    tenant_id: UUID
    language: DocumentLanguage
    chunks: tuple[DocumentChunk, ...]


@dataclass(frozen=True, slots=True)
class ChunkForEmbedding:
    """One chunk's stable identity and text for external embedding."""

    chunk_id: UUID
    text: str


class ChunkRepository(Protocol):
    """Persist chunks owned by one immutable document version."""

    async def create_many(self, command: CreateChunks) -> None:
        """Create ordered chunks and their generated PostgreSQL FTS vectors."""

    async def list_for_embedding(
        self, index_generation_id: UUID, tenant_id: UUID
    ) -> tuple[ChunkForEmbedding, ...]:
        """Return one generation's chunks in deterministic ordinal order."""
