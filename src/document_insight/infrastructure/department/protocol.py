"""Department repository protocol."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DepartmentRecord:
    """Tenant-scoped department metadata for application services."""

    department_id: UUID
    name: str


class DepartmentRepository(Protocol):
    """Persistence operations owned by departments."""

    async def create(self, tenant_id: UUID, name: str) -> UUID:
        """Create and flush one department."""

    async def existing_ids(
        self,
        tenant_id: UUID,
        department_ids: tuple[UUID, ...],
    ) -> set[UUID]:
        """Return requested department identifiers owned by the tenant."""

    async def list_by_ids(
        self, tenant_id: UUID, department_ids: tuple[UUID, ...]
    ) -> tuple[DepartmentRecord, ...]:
        """Return named departments owned by one tenant."""

    async def list_all_ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return every department identifier owned by one tenant."""
