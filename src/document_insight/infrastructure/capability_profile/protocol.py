"""Repository contract for immutable capability-profile reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """Named immutable profile referring to one configuration snapshot."""

    profile_id: UUID
    capability: str
    configuration_snapshot_id: UUID
    status: str = "validated"
    name: str = ""


class CapabilityProfileRepository(Protocol):
    """Read immutable capability profile identity."""

    async def get(self, profile_id: UUID) -> CapabilityProfile | None:
        """Return one capability profile by ID."""

    async def list_all(self) -> tuple[CapabilityProfile, ...]:
        """Return platform capability profiles newest first."""

    async def create(self, profile_id: UUID, capability: str, name: str, snapshot_id: UUID) -> None:
        """Create a draft immutable profile."""

    async def validate(self, profile_id: UUID) -> None:
        """Approve a draft profile without changing its immutable configuration."""
