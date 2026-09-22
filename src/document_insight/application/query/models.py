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


@dataclass(frozen=True, slots=True)
class QueryCitation:
    """One exact passage used as evidence in the returned answer."""

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    page_number: int | None
    quote: str
    relevance_score: float


@dataclass(frozen=True, slots=True)
class QueryEntity:
    """An authorized NER match that contributed only a document-level boost."""

    document_version_id: UUID
    text: str
    label: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Grounded answer and citation-ready evidence returned from a RAG execution."""

    answer: str
    confidence: float
    citations: tuple[QueryCitation, ...]
    entities: tuple[QueryEntity, ...]
