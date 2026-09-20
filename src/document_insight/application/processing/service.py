"""First durable stage of the background processing pipeline."""

from datetime import UTC, datetime
from uuid import UUID

from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.processing.exceptions import (
    NerError,
    ParsingError,
    UnsupportedProcessingMediaTypeError,
)
from document_insight.application.processing.models import canonicalize_entities
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.document_parser.protocol import DocumentParser
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository
from document_insight.infrastructure.entity.protocol import CreateEntities, EntityRepository
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
)
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.ner.protocol import NamedEntityRecognizer
from document_insight.infrastructure.object_storage.protocol import OriginalObjectStorage


class ProcessingService:
    """Claim jobs and persist the idempotent parsing checkpoint."""

    def __init__(
        self,
        jobs: JobRepository,
        document_versions: DocumentVersionRepository,
        extracted_documents: ExtractedDocumentRepository,
        entities: EntityRepository,
        object_storage: OriginalObjectStorage,
        pdf_parser: DocumentParser,
        image_parser: DocumentParser,
        ner: NamedEntityRecognizer,
        transactions: TransactionManager,
    ) -> None:
        self._jobs = jobs
        self._document_versions = document_versions
        self._extracted_documents = extracted_documents
        self._entities = entities
        self._object_storage = object_storage
        self._pdf_parser = pdf_parser
        self._image_parser = image_parser
        self._ner = ner
        self._transactions = transactions

    async def process(self, job_id: UUID) -> None:
        """Resume a job through durable parsing and NER checkpoints."""
        async with self._transactions.begin():
            job = await self._jobs.claim(job_id, datetime.now(UTC))
            if job is None:
                return
            await self._document_versions.mark_processing(job.document_version_id)
            version = await self._document_versions.get_for_processing(
                job.document_version_id, job.tenant_id
            )
            extracted_text = (
                None
                if version is None
                else await self._extracted_documents.get_text(version.document_version_id)
            )
            ner_complete = (
                False
                if version is None
                else await self._extracted_documents.ner_is_complete(version.document_version_id)
            )
        if version is None:
            return
        if extracted_text is None:
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
                await self._fail(job.job_id, version.document_version_id, "document_parsing_failed")
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
            extracted_text = parsed.text
        if ner_complete:
            return
        try:
            ner_result = self._ner.recognize(extracted_text)
        except NerError:
            await self._fail(job.job_id, version.document_version_id, "ner_failed")
            return
        async with self._transactions.begin():
            if not await self._extracted_documents.ner_is_complete(version.document_version_id):
                await self._entities.create_many(
                    CreateEntities(
                        document_version_id=version.document_version_id,
                        tenant_id=version.tenant_id,
                        language=ner_result.language,
                        ner_provider=ner_result.provider_name,
                        ner_model=ner_result.model_name,
                        entities=canonicalize_entities(ner_result.entities),
                    )
                )
                await self._extracted_documents.mark_ner_complete(
                    version.document_version_id, ner_result, datetime.now(UTC)
                )

    async def _fail(self, job_id: UUID, version_id: UUID, error_code: str) -> None:
        """Atomically persist a safe terminal stage failure."""
        async with self._transactions.begin():
            await self._jobs.fail(job_id, error_code, datetime.now(UTC))
            await self._document_versions.mark_failed(version_id)
