"""SQLAlchemy repository for immutable configuration snapshot reads."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.configuration_snapshot.model import ConfigurationSnapshotModel
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshot,
    ConfigurationSnapshotRepository,
)


class SqlAlchemyConfigurationSnapshotRepository(ConfigurationSnapshotRepository):
    """Read configuration JSON without exposing its ORM model."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, snapshot_id: UUID) -> ConfigurationSnapshot | None:
        """Load one immutable snapshot."""
        model = await self._session.scalar(
            select(ConfigurationSnapshotModel).where(ConfigurationSnapshotModel.id == snapshot_id)
        )
        if model is None:
            return None
        return ConfigurationSnapshot(
            snapshot_id=model.id,
            capability=model.capability,
            schema_version=model.schema_version,
            configuration=model.configuration_json,
        )

    async def get_by_fingerprint(
        self, capability: str, fingerprint: str
    ) -> ConfigurationSnapshot | None:
        """Return an existing snapshot with the same canonical content."""
        model = await self._session.scalar(
            select(ConfigurationSnapshotModel).where(
                ConfigurationSnapshotModel.capability == capability,
                ConfigurationSnapshotModel.fingerprint == fingerprint,
            )
        )
        return (
            None
            if model is None
            else ConfigurationSnapshot(
                model.id, model.capability, model.schema_version, model.configuration_json
            )
        )

    async def create(
        self, snapshot_id: UUID, capability: str, fingerprint: str, configuration: dict[str, Any]
    ) -> None:
        """Add one schema-v1 immutable snapshot."""
        self._session.add(
            ConfigurationSnapshotModel(
                id=snapshot_id,
                capability=capability,
                schema_version=1,
                fingerprint=fingerprint,
                configuration_json=configuration,
            )
        )
        await self._session.flush()
