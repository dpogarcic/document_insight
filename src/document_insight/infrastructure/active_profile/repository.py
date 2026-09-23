"""SQLAlchemy repository for active-profile resolution."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.active_profile.model import ActiveProfileModel
from document_insight.infrastructure.active_profile.protocol import (
    ActiveProfile,
    ActiveProfileRepository,
)


class SqlAlchemyActiveProfileRepository(ActiveProfileRepository):
    """Read the only mutable configuration selection state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_ingestion_profile_id(self, scope: str) -> UUID | None:
        """Resolve the active ingestion bundle without falling back to environment values."""
        return await self._session.scalar(
            select(ActiveProfileModel.ingestion_profile_id).where(
                ActiveProfileModel.scope == scope,
                ActiveProfileModel.profile_kind == "ingestion",
            )
        )

    async def get_query_profile_id(self, scope: str) -> UUID | None:
        """Resolve the active query bundle without environment fallback."""
        return await self._session.scalar(
            select(ActiveProfileModel.query_profile_id).where(
                ActiveProfileModel.scope == scope,
                ActiveProfileModel.profile_kind == "query",
            )
        )

    async def lock(self, scope: str, kind: str) -> ActiveProfile | None:
        """Lock a platform pointer for atomic revision checking."""
        model = await self._session.scalar(
            select(ActiveProfileModel)
            .where(
                ActiveProfileModel.scope == scope,
                ActiveProfileModel.profile_kind == kind,
            )
            .with_for_update()
        )
        if model is None:
            return None
        profile_id = model.ingestion_profile_id if kind == "ingestion" else model.query_profile_id
        return None if profile_id is None else ActiveProfile(profile_id, model.revision)

    async def get(self, scope: str, kind: str) -> ActiveProfile | None:
        """Read one active pointer for the operator dashboard."""
        model = await self._session.scalar(
            select(ActiveProfileModel).where(
                ActiveProfileModel.scope == scope,
                ActiveProfileModel.profile_kind == kind,
            )
        )
        if model is None:
            return None
        profile_id = model.ingestion_profile_id if kind == "ingestion" else model.query_profile_id
        return None if profile_id is None else ActiveProfile(profile_id, model.revision)

    async def activate(self, scope: str, kind: str, profile_id: UUID, revision: int) -> None:
        """Set the selected bundle and increment the pointer revision."""
        value = (
            {"ingestion_profile_id": profile_id}
            if kind == "ingestion"
            else {"query_profile_id": profile_id}
        )
        await self._session.execute(
            update(ActiveProfileModel)
            .where(
                ActiveProfileModel.scope == scope,
                ActiveProfileModel.profile_kind == kind,
                ActiveProfileModel.revision == revision,
            )
            .values(**value, revision=revision + 1)
        )
