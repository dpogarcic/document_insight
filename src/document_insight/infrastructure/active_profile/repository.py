"""SQLAlchemy repository for active-profile resolution."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.active_profile.model import ActiveProfileModel
from document_insight.infrastructure.active_profile.protocol import ActiveProfileRepository


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
