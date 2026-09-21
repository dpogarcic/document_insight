"""SQLAlchemy persistence adapter for document-department assignments."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_department.protocol import (
    DocumentDepartmentAssignment,
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

    async def list_for_document_ids(
        self, document_ids: tuple[UUID, ...], tenant_id: UUID
    ) -> tuple[DocumentDepartmentAssignment, ...]:
        """Load associations without allowing a caller to cross tenant scope."""
        if not document_ids:
            return ()
        rows = await self._session.execute(
            select(
                DocumentDepartmentModel.document_id,
                DocumentDepartmentModel.department_id,
            ).where(
                DocumentDepartmentModel.document_id.in_(document_ids),
                DocumentDepartmentModel.tenant_id == tenant_id,
            )
        )
        return tuple(
            DocumentDepartmentAssignment(document_id=document_id, department_id=department_id)
            for document_id, department_id in rows.tuples()
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
