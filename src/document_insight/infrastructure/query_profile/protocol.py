"""Query-profile repository protocol and query-safe resolved data."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResolvedQueryProfile:
    """Immutable query configuration identity and explicitly enabled read cohorts."""

    query_profile_id: UUID
    lexical_profile_ids: tuple[UUID, ...]
    embedding_profile_ids: tuple[UUID, ...]


class QueryProfileRepository(Protocol):
    """Read immutable query-time profile bundles."""

    async def get(self, query_profile_id: UUID) -> ResolvedQueryProfile | None:
        """Return one persisted query profile and its enabled read cohorts."""
