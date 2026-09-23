"""Logical-document repository protocol."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """Logical-document data safe for application-layer authorization."""

    document_id: UUID
    title: str
    current_ready_version_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationDocumentOption:
    """Activated document metadata shown in the operator's suite picker."""

    document_id: UUID
    title: str
    version_id: UUID


class DocumentRepository(Protocol):
    """Persistence operations owned by logical documents."""

    async def exists(self, document_id: UUID, tenant_id: UUID) -> bool:
        """Return whether a tenant owns the logical document."""

    async def list_for_tenant(self, tenant_id: UUID) -> tuple[StoredDocument, ...]:
        """List stable documents for one tenant without department authorization."""

    async def list_active_for_operator(
        self, tenant_id: UUID
    ) -> tuple[EvaluationDocumentOption, ...]:
        """List activated version IDs and titles under metadata-only operator grants."""

    async def lock(self, document_id: UUID, tenant_id: UUID) -> bool:
        """Lock an existing logical document while allocating its next version."""

    async def create(
        self,
        document_id: UUID,
        tenant_id: UUID,
        title: str,
        created_by: UUID,
    ) -> None:
        """Create one logical document."""

    async def get_current_ready_version_id(self, document_id: UUID, tenant_id: UUID) -> UUID | None:
        """Return the current searchable version while the document is locked."""

    async def set_current_ready_version_id(
        self, document_id: UUID, tenant_id: UUID, document_version_id: UUID
    ) -> None:
        """Set one already-ready version as current during explicit activation."""
