"""SQLAlchemy repository for immutable configuration snapshot reads."""

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
