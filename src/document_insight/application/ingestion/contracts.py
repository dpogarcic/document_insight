"""Ports and commands used by document ingestion."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.domain.auth import AuthenticatedUser
from document_insight.domain.ingestion import StoredDocumentVersion, StoredMediaType


@dataclass(frozen=True, slots=True)
class IngestDocumentCommand:
    """Validated transport data and authenticated scope for one upload."""

    content: bytes
    filename: str
    declared_content_type: str | None
    document_id: UUID | None
    department_ids: tuple[UUID, ...]
    actor: AuthenticatedUser


@dataclass(frozen=True, slots=True)
class StoreDocumentVersion:
    """Metadata required to persist an uploaded document version."""

    document_id: UUID
    document_version_id: UUID
    filename: str
    object_key: str
    media_type: StoredMediaType
    size_bytes: int
    content_sha256: str
    requested_department_ids: tuple[UUID, ...]
    actor: AuthenticatedUser
    replaces_existing_document: bool


class OriginalObjectStorage(Protocol):
    """Immutable original-file storage operations required by ingestion."""

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store one original object at a unique key."""

    async def delete(self, key: str) -> None:
        """Delete an object while compensating for a failed metadata write."""


class DocumentRepository(Protocol):
    """Persistence operations required before queue creation exists."""

    async def validate_upload_target(
        self,
        document_id: UUID | None,
        requested_department_ids: tuple[UUID, ...],
        actor: AuthenticatedUser,
    ) -> tuple[UUID, ...]:
        """Authorize the target and return its effective department set."""

    async def create_stored_version(
        self,
        upload: StoreDocumentVersion,
        effective_department_ids: tuple[UUID, ...],
    ) -> StoredDocumentVersion:
        """Persist a new logical document or immutable next version."""
