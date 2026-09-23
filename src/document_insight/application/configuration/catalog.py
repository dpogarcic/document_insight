"""Read-only view models for the private profile operator panel."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from document_insight.infrastructure.active_profile.protocol import (
    ActiveProfile,
    ActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.protocol import (
    CapabilityProfile,
    CapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshotRepository,
)
from document_insight.infrastructure.ingestion_profile.protocol import (
    IngestionProfile,
    IngestionProfileRepository,
)
from document_insight.infrastructure.query_profile.protocol import (
    QueryProfileRepository,
    ResolvedQueryProfile,
)


@dataclass(frozen=True, slots=True)
class ProfileCatalog:
    """One consistent operator view of available and active profiles."""

    capabilities: tuple[CapabilityProfile, ...]
    ingestions: tuple[IngestionProfile, ...]
    queries: tuple[ResolvedQueryProfile, ...]
    active_ingestion: ActiveProfile | None
    active_query: ActiveProfile | None


@dataclass(frozen=True, slots=True)
class CapabilityDetail:
    """A capability profile and its exact immutable configuration."""

    profile: CapabilityProfile
    configuration: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QueryDetail:
    """A query bundle and its exact retrieval settings."""

    profile: ResolvedQueryProfile
    retrieval_configuration: dict[str, Any]


class ProfileCatalogService:
    """Collect repository-owned records for review before activation."""

    def __init__(
        self,
        capabilities: CapabilityProfileRepository,
        ingestions: IngestionProfileRepository,
        queries: QueryProfileRepository,
        snapshots: ConfigurationSnapshotRepository,
        active: ActiveProfileRepository,
    ) -> None:
        self._capabilities = capabilities
        self._ingestions = ingestions
        self._queries = queries
        self._snapshots = snapshots
        self._active = active

    async def list_all(self) -> ProfileCatalog:
        """Return configuration records and platform pointers for one dashboard."""
        return ProfileCatalog(
            await self._capabilities.list_all(),
            await self._ingestions.list_all(),
            await self._queries.list_all(),
            await self._active.get("platform", "ingestion"),
            await self._active.get("platform", "query"),
        )

    async def capability(self, profile_id: UUID) -> CapabilityDetail | None:
        """Load a capability and its snapshot without exposing ORM models."""
        profile = await self._capabilities.get(profile_id)
        if profile is None:
            return None
        snapshot = await self._snapshots.get(profile.configuration_snapshot_id)
        return None if snapshot is None else CapabilityDetail(profile, snapshot.configuration)

    async def ingestion(self, profile_id: UUID) -> IngestionProfile | None:
        """Return an immutable ingestion bundle for review."""
        return await self._ingestions.get(profile_id)

    async def query(self, profile_id: UUID) -> QueryDetail | None:
        """Return a query bundle and its retrieval settings for review."""
        profile = await self._queries.get(profile_id)
        if profile is None:
            return None
        snapshot = await self._snapshots.get(profile.retrieval_snapshot_id)
        return None if snapshot is None else QueryDetail(profile, snapshot.configuration)
