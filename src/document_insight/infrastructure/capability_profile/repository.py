"""SQLAlchemy repository for immutable capability-profile reads."""

from uuid import UUID

from sqlalchemy import select, update
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
            status=model.status,
            name=model.name,
        )

    async def list_all(self) -> tuple[CapabilityProfile, ...]:
        """List profiles without resolving snapshots as a repository side effect."""
        models = await self._session.scalars(
            select(CapabilityProfileModel).order_by(CapabilityProfileModel.created_at.desc())
        )
        return tuple(
            CapabilityProfile(
                model.id,
                model.capability,
                model.configuration_snapshot_id,
                model.status,
                model.name,
            )
            for model in models
        )

    async def create(self, profile_id: UUID, capability: str, name: str, snapshot_id: UUID) -> None:
        """Add one draft profile."""
        self._session.add(
            CapabilityProfileModel(
                id=profile_id,
                capability=capability,
                name=name,
                configuration_snapshot_id=snapshot_id,
                status="draft",
            )
        )

    async def validate(self, profile_id: UUID) -> None:
        """Move a profile from draft to validated."""
        await self._session.execute(
            update(CapabilityProfileModel)
            .where(
                CapabilityProfileModel.id == profile_id, CapabilityProfileModel.status == "draft"
            )
            .values(status="validated")
        )
