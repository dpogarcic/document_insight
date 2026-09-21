"""SQLAlchemy repository for parsed version text."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.processing.models import DocumentLanguage, NerResult
from document_insight.infrastructure.extracted_document.model import ExtractedDocumentModel
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
    NerMetadata,
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

    async def get_text(self, document_version_id: UUID) -> str | None:
        """Load parsed text for downstream processing without exposing the ORM model."""
        text: str | None = await self._session.scalar(
            select(ExtractedDocumentModel.text).where(
                ExtractedDocumentModel.document_version_id == document_version_id
            )
        )
        return text

    async def ner_is_complete(self, document_version_id: UUID) -> bool:
        """Use explicit completion metadata so zero-entity results are checkpointed."""
        completed_at = await self._session.scalar(
            select(ExtractedDocumentModel.ner_completed_at).where(
                ExtractedDocumentModel.document_version_id == document_version_id
            )
        )
        return completed_at is not None

    async def mark_ner_complete(
        self, document_version_id: UUID, result: NerResult, completed_at: datetime
    ) -> None:
        """Record language, provider, model, and completion time atomically with entities."""
        await self._session.execute(
            update(ExtractedDocumentModel)
            .where(ExtractedDocumentModel.document_version_id == document_version_id)
            .values(
                detected_language=result.language.value,
                ner_provider=result.provider_name,
                ner_model=result.model_name,
                ner_completed_at=completed_at,
            )
        )

    async def get_ner_metadata(self, document_version_id: UUID) -> NerMetadata | None:
        """Load the durable language detected by the completed NER stage."""
        language = await self._session.scalar(
            select(ExtractedDocumentModel.detected_language).where(
                ExtractedDocumentModel.document_version_id == document_version_id
            )
        )
        return None if language is None else NerMetadata(DocumentLanguage(language))
