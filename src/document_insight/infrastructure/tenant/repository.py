"""SQLAlchemy persistence adapter for tenants."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.tenant.protocol import TenantRepository, TenantSummary


class SqlAlchemyTenantRepository(TenantRepository):
    """Own persistence operations for tenant records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str) -> UUID:
        """Create and flush one tenant."""
        tenant = TenantModel(name=name)
        self._session.add(tenant)
        await self._session.flush()
        return tenant.id

    async def list_for_operator(self) -> tuple[TenantSummary, ...]:
        """Read only tenant ID and name through the operator's metadata grant."""
        rows = await self._session.execute(
            select(TenantModel.id, TenantModel.name).order_by(TenantModel.name, TenantModel.id)
        )
        return tuple(TenantSummary(identifier, name) for identifier, name in rows)
