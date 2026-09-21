"""Repository contract for immutable ingestion-profile reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IngestionProfile:
    """IDs of exact profiles used for one derived-data generation."""

    ingestion_profile_id: UUID
    ner_profile_id: UUID
    chunking_profile_id: UUID
    lexical_profile_id: UUID
    embedding_profile_id: UUID


class IngestionProfileRepository(Protocol):
    """Read immutable ingestion bundle identity."""

    async def get(self, profile_id: UUID) -> IngestionProfile | None:
        """Return one ingestion profile by ID."""
