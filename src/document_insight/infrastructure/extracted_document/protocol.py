"""Repository contract for parsed version text."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.processing.models import ParsedDocument


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
