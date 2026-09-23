"""Authorization-first retrieval interfaces and typed chunk candidates."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """Trusted predicates every retrieval backend must enforce before scoring."""

    tenant_id: UUID
    department_ids: tuple[UUID, ...]
    allowed_version_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """An authorized chunk and score from one retrieval branch."""

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    title: str
    text: str
    page_number: int | None
    score: float
    start_offset: int = 0
    end_offset: int = 0


@dataclass(frozen=True, slots=True)
class EntityMatch:
    """An authorized document-version entity match used only as a soft boost."""

    document_version_id: UUID
    display_value: str
    label: str


class AuthorizedRetrievalRepository(Protocol):
    """Search only active, authorized chunks and entity metadata."""

    async def find_entity_matches(
        self, scope: RetrievalScope, filter_text: str, limit: int
    ) -> tuple[EntityMatch, ...]:
        """Return matching authorized entity metadata without selecting passages."""

    async def lexical_search(
        self,
        scope: RetrievalScope,
        lexical_profile_id: UUID,
        query_text: str,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        """Rank authorized active chunks from one explicitly enabled lexical cohort."""

    async def vector_search(
        self,
        scope: RetrievalScope,
        embedding_profile_id: UUID,
        vector: tuple[float, ...],
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        """Rank authorized active chunks from one compatible embedding cohort."""
