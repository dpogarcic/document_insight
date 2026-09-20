"""Repository contract for parsed version text."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from document_insight.application.processing.models import NerResult, ParsedDocument


@dataclass(frozen=True, slots=True)
class CreateExtractedDocument:
    """Immutable parsed text to persist for one document version."""

    document_version_id: UUID
    tenant_id: UUID
    parsed: ParsedDocument


class ExtractedDocumentRepository(Protocol):
    """Persistence owned solely by parsed document output."""

    async def exists(self, document_version_id: UUID) -> bool:
        """Return whether parsing has already completed for this version."""

    async def create(self, command: CreateExtractedDocument) -> None:
        """Persist one idempotent extraction result."""

    async def get_text(self, document_version_id: UUID) -> str | None:
        """Return extracted text for downstream processing stages."""

    async def ner_is_complete(self, document_version_id: UUID) -> bool:
        """Return whether NER completed, including an empty entity result."""

    async def mark_ner_complete(
        self, document_version_id: UUID, result: NerResult, completed_at: datetime
    ) -> None:
        """Persist language and provider metadata for the completed NER stage."""
