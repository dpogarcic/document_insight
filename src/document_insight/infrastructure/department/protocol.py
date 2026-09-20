"""Department repository protocol."""

from typing import Protocol
from uuid import UUID


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
