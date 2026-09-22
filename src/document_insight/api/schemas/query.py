"""Request and response schemas for document queries."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from document_insight.api.schemas.common import ApiModel

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class QueryRequest(ApiModel):
    """Question and optional textual retrieval hint supplied to the query service."""

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    filter: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] | None = None
    top_k: Annotated[int, Field(ge=1, le=20)] = 5


class SourceCitationDTO(ApiModel):
    """Exact source passage supporting an answer."""

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    page_number: Annotated[int, Field(ge=1)] | None = None
    quote: NonEmptyText
    relevance_score: Annotated[float, Field(ge=0.0, le=1.0)]


class DetectedEntityDTO(ApiModel):
    """Authorized document-version entity that softly assisted retrieval."""

    text: NonEmptyText
    label: NonEmptyText
    document_version_id: UUID


class QueryDTO(ApiModel):
    """Evidence-grounded answer returned after authorized hybrid retrieval."""

    answer: NonEmptyText
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    sources: list[SourceCitationDTO]
    entities: list[DetectedEntityDTO]
