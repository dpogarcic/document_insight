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


class CapabilityProfileRepository(Protocol):
    """Read immutable capability profile identity."""

    async def get(self, profile_id: UUID) -> CapabilityProfile | None:
        """Return one capability profile by ID."""
