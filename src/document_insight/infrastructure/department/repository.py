"""SQLAlchemy persistence adapter for departments."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.department.protocol import DepartmentRepository


class SqlAlchemyDepartmentRepository(DepartmentRepository):
    """Own persistence operations for department records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: UUID, name: str) -> UUID:
        """Create and flush one department."""
        department = DepartmentModel(tenant_id=tenant_id, name=name)
        self._session.add(department)
        await self._session.flush()
        return department.id

    async def existing_ids(self, tenant_id: UUID, department_ids: tuple[UUID, ...]) -> set[UUID]:
        """Return requested department IDs that belong to the tenant."""
        return set(
            await self._session.scalars(
                select(DepartmentModel.id).where(
                    DepartmentModel.tenant_id == tenant_id,
                    DepartmentModel.id.in_(department_ids),
                )
            )
        )
