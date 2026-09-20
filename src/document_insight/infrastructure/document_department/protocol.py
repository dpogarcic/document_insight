"""Document-department association repository protocol."""

from typing import Protocol
from uuid import UUID


class DocumentDepartmentRepository(Protocol):
    """Persistence operations owned by document-department associations."""

    async def list_department_ids(self, document_id: UUID, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return the logical document's department assignments."""

    async def add_many(
        self,
        document_id: UUID,
        tenant_id: UUID,
        department_ids: tuple[UUID, ...],
    ) -> None:
        """Create the logical document's initial department assignments."""
