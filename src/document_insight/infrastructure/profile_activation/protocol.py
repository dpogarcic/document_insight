"""Append-only audit contract for platform profile activation."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateProfileActivation:
    """The complete audit entry for one successful pointer change."""

    scope: str
    kind: str
    previous_profile_id: UUID
    new_profile_id: UUID
    actor_id: UUID
    reason: str
    revision: int


class ProfileActivationRepository(Protocol):
    """Persist successful switches without modifying previous audit records."""

    async def create(self, activation: CreateProfileActivation) -> None:
        """Append an activation record in the pointer transaction."""
