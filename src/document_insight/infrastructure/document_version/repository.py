"""SQLAlchemy persistence adapter for immutable document versions."""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.ingestion.models import (
    DocumentMediaType,
    DocumentVersionStatus,
)
from document_insight.infrastructure.document_version.model import DocumentVersionModel
from document_insight.infrastructure.document_version.protocol import (
    CreateDocumentVersion,
    DocumentVersionRepository,
    ProcessingDocumentVersion,
)


class SqlAlchemyDocumentVersionRepository(DocumentVersionRepository):
    """Own persistence operations for immutable document-version records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_version_number(self, document_id: UUID) -> int:
        """Return the next number after the highest persisted document version."""
        current = await self._session.scalar(
            select(func.max(DocumentVersionModel.version_number)).where(
                DocumentVersionModel.document_id == document_id
            )
        )
        return (current or 0) + 1

    async def get_document_id(self, version_id: UUID, tenant_id: UUID) -> UUID | None:
        """Return the logical document owning one tenant-scoped version."""
        document_id: UUID | None = await self._session.scalar(
            select(DocumentVersionModel.document_id).where(
                DocumentVersionModel.id == version_id,
                DocumentVersionModel.tenant_id == tenant_id,
            )
        )
        return document_id

    async def create(self, command: CreateDocumentVersion) -> None:
        """Create one immutable stored document version."""
        self._session.add(
            DocumentVersionModel(
                id=command.document_version_id,
                document_id=command.document_id,
                tenant_id=command.tenant_id,
                version_number=command.version_number,
                original_filename=command.original_filename,
                object_key=command.object_key,
                media_type=command.media_type.value,
                size_bytes=command.size_bytes,
                content_sha256=bytes.fromhex(command.content_sha256),
                status=command.status.value,
                created_by=command.created_by,
            )
        )

    async def get_for_processing(
        self, version_id: UUID, tenant_id: UUID
    ) -> ProcessingDocumentVersion | None:
        """Load immutable source metadata for a worker job."""
        version = await self._session.scalar(
            select(DocumentVersionModel).where(
                DocumentVersionModel.id == version_id,
                DocumentVersionModel.tenant_id == tenant_id,
            )
        )
        if version is None:
            return None
        return ProcessingDocumentVersion(
            document_version_id=version.id,
            tenant_id=version.tenant_id,
            object_key=version.object_key,
            media_type=DocumentMediaType(version.media_type),
        )

    async def mark_processing(self, version_id: UUID) -> None:
        """Mirror job processing state on its immutable version."""
        await self._session.execute(
            update(DocumentVersionModel)
            .where(DocumentVersionModel.id == version_id)
            .values(status=DocumentVersionStatus.PROCESSING.value)
        )

    async def mark_failed(self, version_id: UUID) -> None:
        """Mirror a terminal worker failure on its immutable version."""
        await self._session.execute(
            update(DocumentVersionModel)
            .where(DocumentVersionModel.id == version_id)
            .values(status=DocumentVersionStatus.FAILED.value)
        )

    async def mark_ready(self, version_id: UUID) -> None:
        """Mark one complete derived-data version ready for promotion."""
        await self._session.execute(
            update(DocumentVersionModel)
            .where(DocumentVersionModel.id == version_id)
            .values(status=DocumentVersionStatus.READY.value)
        )

    async def is_newer_than(self, candidate_id: UUID, current_id: UUID) -> bool:
        """Compare immutable version numbers without leaking another tenant's metadata."""
        candidate = await self._session.scalar(
            select(DocumentVersionModel.document_id, DocumentVersionModel.version_number).where(
                DocumentVersionModel.id == candidate_id
            )
        )
        current = await self._session.scalar(
            select(DocumentVersionModel.document_id, DocumentVersionModel.version_number).where(
                DocumentVersionModel.id == current_id
            )
        )
        return (
            candidate is not None
            and current is not None
            and candidate.document_id == current.document_id
            and candidate.version_number > current.version_number
        )
