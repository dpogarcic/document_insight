"""SQLAlchemy repository for immutable capability-profile reads."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.capability_profile.model import CapabilityProfileModel
from document_insight.infrastructure.capability_profile.protocol import (
    CapabilityProfile,
    CapabilityProfileRepository,
)


class SqlAlchemyCapabilityProfileRepository(CapabilityProfileRepository):
    """Read profile identity without loading configuration JSON indirectly."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: UUID) -> CapabilityProfile | None:
        """Load one immutable profile."""
        model = await self._session.scalar(
            select(CapabilityProfileModel).where(CapabilityProfileModel.id == profile_id)
        )
        if model is None:
            return None
        return CapabilityProfile(
            profile_id=model.id,
            capability=model.capability,
            configuration_snapshot_id=model.configuration_snapshot_id,
        )
