"""Tenant repository protocol."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantSummary:
    """Non-content metadata available to a platform operator."""

    tenant_id: UUID
    name: str


class TenantRepository(Protocol):
    """Persistence operations owned by tenants."""

    async def create(self, name: str) -> UUID:
        """Create and flush one tenant."""

    async def list_for_operator(self) -> tuple[TenantSummary, ...]:
        """List tenant identifiers and names without document access."""
