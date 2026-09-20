"""SQLAlchemy persistence adapter for user-department memberships."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.user_department.model import UserDepartmentModel
from document_insight.infrastructure.user_department.protocol import UserDepartmentRepository


class SqlAlchemyUserDepartmentRepository(UserDepartmentRepository):
    """Own persistence operations for user-department associations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: UUID, department_id: UUID, tenant_id: UUID) -> None:
        """Create one user-department association."""
        self._session.add(
            UserDepartmentModel(
                user_id=user_id,
                department_id=department_id,
                tenant_id=tenant_id,
            )
        )

    async def list_department_ids(self, user_id: UUID, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return ordered memberships for one tenant-scoped user."""
        return tuple(
            await self._session.scalars(
                select(UserDepartmentModel.department_id)
                .where(
                    UserDepartmentModel.user_id == user_id,
                    UserDepartmentModel.tenant_id == tenant_id,
                )
                .order_by(UserDepartmentModel.department_id)
            )
        )
