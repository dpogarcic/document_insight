"""Repository contract for version-scoped index generations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateIndexGeneration:
    """One generation target resolved before a processing job is created."""

    index_generation_id: UUID
    tenant_id: UUID
    document_version_id: UUID
    ingestion_profile_id: UUID


@dataclass(frozen=True, slots=True)
class IndexGeneration:
    """Durable generation identity used to resume a processing job."""

    index_generation_id: UUID
    ingestion_profile_id: UUID
    chunking_completed_at: datetime | None
    embedding_completed_at: datetime | None


class IndexGenerationRepository(Protocol):
    """Own derived-data generation records for document versions."""

    async def create(self, command: CreateIndexGeneration) -> None:
        """Create a building generation exactly once."""

    async def get(self, index_generation_id: UUID, tenant_id: UUID) -> IndexGeneration | None:
        """Return worker-required identity for one generation."""

    async def mark_chunking_complete(
        self, index_generation_id: UUID, completed_at: datetime
    ) -> None:
        """Persist atomic chunking and lexical-index completion for one generation."""

    async def mark_embedding_complete(
        self, index_generation_id: UUID, completed_at: datetime
    ) -> None:
        """Persist successful vectors for the generation's embedding profile."""

    async def mark_ready(self, index_generation_id: UUID) -> None:
        """Mark a generation ready only after all derived stages are complete."""

    async def referenced_ingestion_profile_ids(self) -> tuple[UUID, ...]:
        """Return profiles still referenced by completed searchable generations."""
