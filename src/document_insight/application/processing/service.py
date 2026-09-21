"""First durable stage of the background processing pipeline."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from document_insight.application.configuration.exceptions import InvalidProcessingProfileError
from document_insight.application.configuration.models import EmbeddingConfiguration
from document_insight.application.configuration.service import IngestionProfileResolver
from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.processing.exceptions import (
    EmbeddingError,
    NerError,
    ParsingError,
    UnsupportedProcessingMediaTypeError,
)
from document_insight.application.processing.models import canonicalize_entities
from document_insight.infrastructure.chunk.protocol import (
    ChunkForEmbedding,
    ChunkRepository,
    CreateChunks,
)
from document_insight.infrastructure.chunk_embedding.protocol import (
    ChunkEmbedding,
    ChunkEmbeddingRepository,
    CreateChunkEmbeddings,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.document_chunker.protocol import DocumentChunkerFactory
from document_insight.infrastructure.document_parser.protocol import DocumentParser
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository
from document_insight.infrastructure.embedding.protocol import TextEmbedderFactory
from document_insight.infrastructure.entity.protocol import CreateEntities, EntityRepository
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
)
from document_insight.infrastructure.index_generation.protocol import IndexGenerationRepository
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.ner.protocol import NamedEntityRecognizerFactory
from document_insight.infrastructure.object_storage.protocol import OriginalObjectStorage

logger = logging.getLogger(__name__)


class ProcessingService:
    """Claim jobs and persist the idempotent parsing checkpoint."""

    def __init__(
        self,
        jobs: JobRepository,
        document_versions: DocumentVersionRepository,
        extracted_documents: ExtractedDocumentRepository,
        entities: EntityRepository,
        chunks: ChunkRepository,
        chunk_embeddings: ChunkEmbeddingRepository,
        index_generations: IndexGenerationRepository,
        profile_resolver: IngestionProfileResolver,
        object_storage: OriginalObjectStorage,
        pdf_parser: DocumentParser,
        image_parser: DocumentParser,
        ner_recognizers: NamedEntityRecognizerFactory,
        chunkers: DocumentChunkerFactory,
        embedders: TextEmbedderFactory,
        transactions: TransactionManager,
    ) -> None:
        self._jobs = jobs
        self._document_versions = document_versions
        self._extracted_documents = extracted_documents
        self._entities = entities
        self._chunks = chunks
        self._chunk_embeddings = chunk_embeddings
        self._index_generations = index_generations
        self._profile_resolver = profile_resolver
        self._object_storage = object_storage
        self._pdf_parser = pdf_parser
        self._image_parser = image_parser
        self._ner_recognizers = ner_recognizers
        self._chunkers = chunkers
        self._embedders = embedders
        self._transactions = transactions

    async def process(self, job_id: UUID) -> None:
        """Resume a job through durable parsing and NER checkpoints."""
        profile_error: str | None = None
        profile = None
        chunker = None
        generation = None
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
            if (
                version is not None
                and job.ingestion_profile_id is not None
                and job.index_generation_id is not None
            ):
                generation = await self._index_generations.get(
                    job.index_generation_id, version.tenant_id
                )
                if (
                    generation is None
                    or generation.ingestion_profile_id != job.ingestion_profile_id
                ):
                    profile_error = "index_generation_missing"
                else:
                    try:
                        profile = await self._profile_resolver.resolve(job.ingestion_profile_id)
                        chunker = self._chunkers.create(profile.chunking)
                    except (InvalidProcessingProfileError, ValueError):
                        profile_error = "processing_profile_invalid"
        if version is None:
            return
        if job.ingestion_profile_id is None or job.index_generation_id is None:
            await self._fail(job.job_id, version.document_version_id, "processing_profile_missing")
            return
        if profile_error is not None:
            await self._fail(job.job_id, version.document_version_id, profile_error)
            return
        assert generation is not None
        assert profile is not None
        assert chunker is not None
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
            async with self._transactions.begin():
                ner_metadata = await self._extracted_documents.get_ner_metadata(
                    version.document_version_id
                )
            if ner_metadata is None:
                await self._fail(job.job_id, version.document_version_id, "ner_metadata_missing")
                return
            language = ner_metadata.language
        else:
            try:
                ner = self._ner_recognizers.create(profile.ner)
                ner_result = ner.recognize(extracted_text)
            except (NerError, ValueError):
                await self._fail(job.job_id, version.document_version_id, "ner_failed")
                return
            language = ner_result.language
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
        if generation.chunking_completed_at is None:
            chunks = chunker.chunk(extracted_text)
            async with self._transactions.begin():
                current_generation = await self._index_generations.get(
                    job.index_generation_id, version.tenant_id
                )
                if (
                    current_generation is not None
                    and current_generation.chunking_completed_at is None
                ):
                    await self._chunks.create_many(
                        CreateChunks(
                            document_version_id=version.document_version_id,
                            index_generation_id=job.index_generation_id,
                            tenant_id=version.tenant_id,
                            language=language,
                            chunks=chunks,
                        )
                    )
                    await self._index_generations.mark_chunking_complete(
                        job.index_generation_id, datetime.now(UTC)
                    )
        if generation.embedding_completed_at is None:
            async with self._transactions.begin():
                chunks_to_embed = await self._chunks.list_for_embedding(
                    job.index_generation_id, version.tenant_id
                )
            try:
                embeddings = await self._embed_chunks(chunks_to_embed, profile.embedding)
            except (EmbeddingError, ValueError) as error:
                logger.exception(
                    "Embedding stage failed: %s",
                    str(error) or "profile_or_provider_error",
                    extra={
                        "job_id": str(job.job_id),
                        "document_version_id": str(version.document_version_id),
                        "error_code": "embedding_failed",
                    },
                )
                await self._fail(job.job_id, version.document_version_id, "embedding_failed")
                return
            async with self._transactions.begin():
                current_generation = await self._index_generations.get(
                    job.index_generation_id, version.tenant_id
                )
                if (
                    current_generation is not None
                    and current_generation.embedding_completed_at is None
                ):
                    await self._chunk_embeddings.create_many(
                        CreateChunkEmbeddings(profile.embedding_profile_id, embeddings)
                    )
                    await self._index_generations.mark_embedding_complete(
                        job.index_generation_id, datetime.now(UTC)
                    )
        await self._complete(job.job_id, version.document_version_id, job.index_generation_id)

    async def _embed_chunks(
        self,
        chunks: tuple[ChunkForEmbedding, ...],
        configuration: EmbeddingConfiguration,
    ) -> tuple[ChunkEmbedding, ...]:
        """Generate stable profile-bound vectors in bounded provider batches."""
        embedder = self._embedders.create(configuration)
        result: list[ChunkEmbedding] = []
        for offset in range(0, len(chunks), configuration.batch_size):
            batch = chunks[offset : offset + configuration.batch_size]
            vectors = await embedder.embed(tuple(chunk.text for chunk in batch), configuration)
            if len(vectors) != len(batch):
                raise EmbeddingError
            result.extend(
                ChunkEmbedding(chunk.chunk_id, vector)
                for chunk, vector in zip(batch, vectors, strict=True)
            )
        return tuple(result)

    async def _fail(self, job_id: UUID, version_id: UUID, error_code: str) -> None:
        """Atomically persist a safe terminal stage failure."""
        async with self._transactions.begin():
            await self._jobs.fail(job_id, error_code, datetime.now(UTC))
            await self._document_versions.mark_failed(version_id)

    async def _complete(self, job_id: UUID, version_id: UUID, index_generation_id: UUID) -> None:
        """Atomically finish processing without activating the ready version."""
        async with self._transactions.begin():
            await self._document_versions.mark_ready(version_id)
            await self._index_generations.mark_ready(index_generation_id)
            await self._jobs.mark_ready(job_id, datetime.now(UTC))
