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
