"""Tenant repository protocol."""

from typing import Protocol
from uuid import UUID


class TenantRepository(Protocol):
    """Persistence operations owned by tenants."""

    async def create(self, name: str) -> UUID:
        """Create and flush one tenant."""
