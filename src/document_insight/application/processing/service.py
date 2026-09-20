"""First durable stage of the background processing pipeline."""

from datetime import UTC, datetime
from uuid import UUID

from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.processing.exceptions import (
    ParsingError,
    UnsupportedProcessingMediaTypeError,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.document_parser.protocol import DocumentParser
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
)
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.object_storage.protocol import OriginalObjectStorage


class ProcessingService:
    """Claim jobs and persist the idempotent parsing checkpoint."""

    def __init__(
        self,
        jobs: JobRepository,
        document_versions: DocumentVersionRepository,
        extracted_documents: ExtractedDocumentRepository,
        object_storage: OriginalObjectStorage,
        pdf_parser: DocumentParser,
        image_parser: DocumentParser,
        transactions: TransactionManager,
    ) -> None:
        self._jobs = jobs
        self._document_versions = document_versions
        self._extracted_documents = extracted_documents
        self._object_storage = object_storage
        self._pdf_parser = pdf_parser
        self._image_parser = image_parser
        self._transactions = transactions

    async def process(self, job_id: UUID) -> None:
        """Parse a queued PDF once; later stages intentionally remain pending."""
        async with self._transactions.begin():
            job = await self._jobs.claim(job_id, datetime.now(UTC))
            if job is None:
                return
            await self._document_versions.mark_processing(job.document_version_id)
            version = await self._document_versions.get_for_processing(
                job.document_version_id, job.tenant_id
            )
            completed = version is not None and await self._extracted_documents.exists(
                version.document_version_id
            )
        if version is None or completed:
            return
        try:
            parser = (
                self._pdf_parser
                if version.media_type is DocumentMediaType.PDF
                else self._image_parser
            )
            if version.media_type not in {
                DocumentMediaType.PDF,
                DocumentMediaType.PNG,
                DocumentMediaType.JPEG,
            }:
                raise UnsupportedProcessingMediaTypeError
            parsed = parser.parse(await self._object_storage.get(version.object_key))
        except ParsingError:
            async with self._transactions.begin():
                await self._jobs.fail(job.job_id, "document_parsing_failed", datetime.now(UTC))
                await self._document_versions.mark_failed(version.document_version_id)
            return
        async with self._transactions.begin():
            if not await self._extracted_documents.exists(version.document_version_id):
                await self._extracted_documents.create(
                    CreateExtractedDocument(
                        document_version_id=version.document_version_id,
                        tenant_id=version.tenant_id,
                        parsed=parsed,
                    )
                )
