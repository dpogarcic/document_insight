"""Document-department association repository protocol."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentDepartmentAssignment:
    """One source-of-truth department association for a logical document."""

    document_id: UUID
    department_id: UUID


class DocumentDepartmentRepository(Protocol):
    """Persistence operations owned by document-department associations."""

    async def list_department_ids(self, document_id: UUID, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return the logical document's department assignments."""

    async def list_for_document_ids(
        self, document_ids: tuple[UUID, ...], tenant_id: UUID
    ) -> tuple[DocumentDepartmentAssignment, ...]:
        """Return assignments for a tenant-scoped set of logical documents."""

    async def add_many(
        self,
        document_id: UUID,
        tenant_id: UUID,
        department_ids: tuple[UUID, ...],
    ) -> None:
        """Create the logical document's initial department assignments."""
