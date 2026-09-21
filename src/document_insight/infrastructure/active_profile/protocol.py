"""Repository contract for explicitly selected runtime bundles."""

from typing import Protocol
from uuid import UUID


class ActiveProfileRepository(Protocol):
    """Resolve active profiles; activation control-plane writes come later."""

    async def get_ingestion_profile_id(self, scope: str) -> UUID | None:
        """Return the explicitly active ingestion profile for one scope."""

    async def get_query_profile_id(self, scope: str) -> UUID | None:
        """Return the explicitly active query profile for one scope."""
