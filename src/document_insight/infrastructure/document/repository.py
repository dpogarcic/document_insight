"""SQLAlchemy persistence adapter for logical documents."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document.protocol import DocumentRepository


class SqlAlchemyDocumentRepository(DocumentRepository):
    """Own persistence operations for stable logical documents."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, document_id: UUID, tenant_id: UUID) -> bool:
        """Return whether a logical document exists inside the tenant."""
        return (
            await self._session.scalar(
                select(DocumentModel.id).where(
                    DocumentModel.id == document_id,
                    DocumentModel.tenant_id == tenant_id,
                )
            )
            is not None
        )

    async def lock(self, document_id: UUID, tenant_id: UUID) -> bool:
        """Lock a logical document while its next version is allocated."""
        return (
            await self._session.scalar(
                select(DocumentModel.id)
                .where(
                    DocumentModel.id == document_id,
                    DocumentModel.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            is not None
        )

    async def create(
        self,
        document_id: UUID,
        tenant_id: UUID,
        title: str,
        created_by: UUID,
    ) -> None:
        """Create one stable logical document."""
        self._session.add(
            DocumentModel(
                id=document_id,
                tenant_id=tenant_id,
                title=title,
                created_by=created_by,
            )
        )

    async def get_current_ready_version_id(self, document_id: UUID, tenant_id: UUID) -> UUID | None:
        """Read the current pointer under the caller's document lock."""
        return await self._session.scalar(
            select(DocumentModel.current_ready_version_id).where(
                DocumentModel.id == document_id,
                DocumentModel.tenant_id == tenant_id,
            )
        )

    async def set_current_ready_version_id(
        self, document_id: UUID, tenant_id: UUID, document_version_id: UUID
    ) -> None:
        """Update only the logical document's searchable-version pointer."""
        await self._session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id, DocumentModel.tenant_id == tenant_id)
            .values(current_ready_version_id=document_version_id)
        )
