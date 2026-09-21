"""Repository contract for immutable configuration snapshots."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """Persisted non-secret JSON configuration with stable identity."""

    snapshot_id: UUID
    capability: str
    schema_version: int
    configuration: dict[str, Any]


class ConfigurationSnapshotRepository(Protocol):
    """Read immutable snapshot content without mutating it."""

    async def get(self, snapshot_id: UUID) -> ConfigurationSnapshot | None:
        """Return one immutable snapshot by ID."""
