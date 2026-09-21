"""Document-version repository protocol and creation data."""

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class ProcessingDocumentVersion:
    """Stored source metadata required by the worker."""

    document_version_id: UUID
    tenant_id: UUID
    object_key: str
    media_type: DocumentMediaType


@dataclass(frozen=True, slots=True)
class LatestDocumentVersion:
    """Most recent immutable version displayed in the document library."""

    document_id: UUID
    document_version_id: UUID
    version_number: int
    original_filename: str
    status: DocumentVersionStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActivatableDocumentVersion:
    """Version ownership and lifecycle state needed for explicit activation."""

    document_id: UUID
    status: DocumentVersionStatus


class DocumentVersionRepository(Protocol):
    """Persistence operations owned by immutable document versions."""

    async def next_version_number(self, document_id: UUID) -> int:
        """Return the next version number while the logical document is locked."""

    async def create(self, command: CreateDocumentVersion) -> None:
        """Create one immutable stored document version."""

    async def get_document_id(self, version_id: UUID, tenant_id: UUID) -> UUID | None:
        """Return the logical document owning a tenant-scoped version."""

    async def list_latest_for_document_ids(
        self, document_ids: tuple[UUID, ...], tenant_id: UUID
    ) -> tuple[LatestDocumentVersion, ...]:
        """Return the newest version for each tenant-scoped logical document."""

    async def list_for_document_ids(
        self, document_ids: tuple[UUID, ...], tenant_id: UUID
    ) -> tuple[LatestDocumentVersion, ...]:
        """Return all immutable versions for a tenant-scoped document set, newest first."""

    async def get_for_activation(
        self, document_version_id: UUID, tenant_id: UUID
    ) -> ActivatableDocumentVersion | None:
        """Return tenant-scoped version ownership and status for activation validation."""

    async def get_for_processing(
        self, version_id: UUID, tenant_id: UUID
    ) -> ProcessingDocumentVersion | None:
        """Return source metadata for a worker-owned version."""

    async def mark_processing(self, version_id: UUID) -> None:
        """Mark a version as processing after its job is claimed."""

    async def mark_failed(self, version_id: UUID) -> None:
        """Mark a version as terminally failed after a non-retryable error."""

    async def mark_ready(self, version_id: UUID) -> None:
        """Mark a fully indexed version ready for explicit administrator activation."""

    async def is_newer_than(self, candidate_id: UUID, current_id: UUID) -> bool:
        """Compare immutable version numbers belonging to one logical document."""
