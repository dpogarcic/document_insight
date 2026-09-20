"""Document-version repository protocol and creation data."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.ingestion.models import (
    DocumentMediaType,
    DocumentVersionStatus,
)


@dataclass(frozen=True, slots=True)
class CreateDocumentVersion:
    """Persistence data for one immutable document version."""

    document_id: UUID
    document_version_id: UUID
    tenant_id: UUID
    version_number: int
    original_filename: str
    object_key: str
    media_type: DocumentMediaType
    size_bytes: int
    content_sha256: str
    created_by: UUID
    status: DocumentVersionStatus = DocumentVersionStatus.STORED


class DocumentVersionRepository(Protocol):
    """Persistence operations owned by immutable document versions."""

    async def next_version_number(self, document_id: UUID) -> int:
        """Return the next version number while the logical document is locked."""

    async def create(self, command: CreateDocumentVersion) -> None:
        """Create one immutable stored document version."""

    async def get_document_id(self, version_id: UUID, tenant_id: UUID) -> UUID | None:
        """Return the logical document owning a tenant-scoped version."""
