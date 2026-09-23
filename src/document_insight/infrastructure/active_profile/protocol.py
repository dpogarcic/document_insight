"""Repository contract for explicitly selected runtime bundles."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActiveProfile:
    """Current pointer and optimistic concurrency revision."""

    profile_id: UUID
    revision: int


class ActiveProfileRepository(Protocol):
    """Resolve active profiles; activation control-plane writes come later."""

    async def get_ingestion_profile_id(self, scope: str) -> UUID | None:
        """Return the explicitly active ingestion profile for one scope."""

    async def get_query_profile_id(self, scope: str) -> UUID | None:
        """Return the explicitly active query profile for one scope."""

    async def lock(self, scope: str, kind: str) -> ActiveProfile | None:
        """Lock and return the pointer inside a shared transaction."""

    async def get(self, scope: str, kind: str) -> ActiveProfile | None:
        """Read a pointer and revision without locking it."""

    async def activate(self, scope: str, kind: str, profile_id: UUID, revision: int) -> None:
        """Advance one locked pointer to its approved bundle."""
