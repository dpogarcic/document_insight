"""SQLAlchemy persistence adapter for document-department assignments."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_department.protocol import (
    DocumentDepartmentRepository,
)


class SqlAlchemyDocumentDepartmentRepository(DocumentDepartmentRepository):
    """Own persistence operations for document-department associations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_department_ids(self, document_id: UUID, tenant_id: UUID) -> tuple[UUID, ...]:
        """Return the departments assigned to a tenant-scoped document."""
        return tuple(
            await self._session.scalars(
                select(DocumentDepartmentModel.department_id).where(
                    DocumentDepartmentModel.document_id == document_id,
                    DocumentDepartmentModel.tenant_id == tenant_id,
                )
            )
        )

    async def add_many(
        self,
        document_id: UUID,
        tenant_id: UUID,
        department_ids: tuple[UUID, ...],
    ) -> None:
        """Create a logical document's initial department assignments."""
        self._session.add_all(
            DocumentDepartmentModel(
                document_id=document_id,
                department_id=department_id,
                tenant_id=tenant_id,
            )
            for department_id in department_ids
        )
