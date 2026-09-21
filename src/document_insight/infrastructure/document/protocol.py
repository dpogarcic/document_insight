"""Logical-document repository protocol."""

from typing import Protocol
from uuid import UUID


class DocumentRepository(Protocol):
    """Persistence operations owned by logical documents."""

    async def exists(self, document_id: UUID, tenant_id: UUID) -> bool:
        """Return whether a tenant owns the logical document."""

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
