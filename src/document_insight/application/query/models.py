"""Typed handoff from query authorization to future retrieval adapters."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthorizedRetrievalRequest:
    """The complete immutable input future retrieval must enforce before scoring."""

    question: str
    query_profile_id: UUID
    lexical_profile_ids: tuple[UUID, ...]
    embedding_profile_ids: tuple[UUID, ...]
    tenant_id: UUID
    department_ids: tuple[UUID, ...]
    filter_text: str | None
    top_k: int
