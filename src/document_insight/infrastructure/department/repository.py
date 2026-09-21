"""SQLAlchemy persistence adapter for departments."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.department.protocol import (
    DepartmentRecord,
    DepartmentRepository,
)


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

    async def list_by_ids(
        self, tenant_id: UUID, department_ids: tuple[UUID, ...]
    ) -> tuple[DepartmentRecord, ...]:
        """Load display metadata for a tenant-scoped department set."""
        if not department_ids:
            return ()
        departments = await self._session.scalars(
            select(DepartmentModel)
            .where(
                DepartmentModel.tenant_id == tenant_id,
                DepartmentModel.id.in_(department_ids),
            )
            .order_by(DepartmentModel.name)
        )
        return tuple(
            DepartmentRecord(department_id=department.id, name=department.name)
            for department in departments
        )

    async def list_all_ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return the complete tenant department set for an administrator scope."""
        return tuple(
            await self._session.scalars(
                select(DepartmentModel.id)
                .where(DepartmentModel.tenant_id == tenant_id)
                .order_by(DepartmentModel.name)
            )
        )
