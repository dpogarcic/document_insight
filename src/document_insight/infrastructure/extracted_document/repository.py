"""SQLAlchemy repository for parsed version text."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.extracted_document.model import ExtractedDocumentModel
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
)


class SqlAlchemyExtractedDocumentRepository(ExtractedDocumentRepository):
    """Own parsed-text persistence without mutating other entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, document_version_id: UUID) -> bool:
        """Check the durable parsing checkpoint for one version."""
        return (
            await self._session.scalar(
                select(ExtractedDocumentModel.document_version_id).where(
                    ExtractedDocumentModel.document_version_id == document_version_id
                )
            )
            is not None
        )

    async def create(self, command: CreateExtractedDocument) -> None:
        """Persist parsed output once under the immutable version ID."""
        self._session.add(
            ExtractedDocumentModel(
                document_version_id=command.document_version_id,
                tenant_id=command.tenant_id,
                text=command.parsed.text,
                page_count=command.parsed.page_count,
                parser_name=command.parsed.parser_name,
                parser_version=command.parsed.parser_version,
            )
        )
