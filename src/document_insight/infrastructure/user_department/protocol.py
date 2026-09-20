"""User-department association repository protocol."""

from typing import Protocol
from uuid import UUID


class UserDepartmentRepository(Protocol):
    """Persistence operations owned by user-department associations."""

    async def add(self, user_id: UUID, department_id: UUID, tenant_id: UUID) -> None:
        """Create one user-department membership."""

    async def list_department_ids(self, user_id: UUID, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return the user's ordered department identifiers."""
