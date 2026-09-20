"""SQLAlchemy persistence adapter for tenants."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.tenant.protocol import TenantRepository


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
