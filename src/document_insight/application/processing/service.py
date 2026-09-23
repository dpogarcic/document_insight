"""First durable stage of the background processing pipeline."""

import logging
from datetime import UTC, datetime
from time import perf_counter, time
from uuid import UUID

from document_insight.application.configuration.exceptions import InvalidProcessingProfileError
from document_insight.application.configuration.models import (
    EmbeddingConfiguration,
    ResolvedIngestionProfile,
)
from document_insight.application.configuration.service import IngestionProfileResolver
from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.jobs.models import ProcessingJob
from document_insight.application.processing.exceptions import (
    EmbeddingError,
    NerError,
    ParsingError,
    UnsupportedProcessingMediaTypeError,
)
from document_insight.application.processing.models import (
    canonicalize_entities,
)
from document_insight.application.processing.retry import RetryCoordinator
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
from document_insight.infrastructure.document_chunker.protocol import (
    DocumentChunker,
    DocumentChunkerFactory,
)
from document_insight.infrastructure.document_parser.protocol import DocumentParser
from document_insight.infrastructure.document_version.protocol import (
    DocumentVersionRepository,
    ProcessingDocumentVersion,
)
from document_insight.infrastructure.embedding.protocol import TextEmbedderFactory
from document_insight.infrastructure.entity.protocol import CreateEntities, EntityRepository
from document_insight.infrastructure.extracted_document.protocol import (
    CreateExtractedDocument,
    ExtractedDocumentRepository,
)
from document_insight.infrastructure.index_generation.protocol import (
    IndexGeneration,
    IndexGenerationRepository,
)
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.ner.protocol import NamedEntityRecognizerFactory
from document_insight.infrastructure.object_storage.protocol import OriginalObjectStorage
from document_insight.infrastructure.observability.processing_job_metrics import (
    INGESTION_JOB_EVENTS,
    INGESTION_STAGE_DURATION,
    INGESTION_TERMINAL_FAILURES,
    INGESTION_WORKER_LAST_SUCCESS,
)
from document_insight.infrastructure.queue.protocol import ProcessingQueue

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
        queue: ProcessingQueue | None = None,
        retry_coordinator: RetryCoordinator | None = None,
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
        self._queue = queue
        self._retry = retry_coordinator or RetryCoordinator(jobs, queue=queue)

    async def process(self, job_id: UUID) -> None:
        """Resume a job through durable parsing and NER checkpoints.

        On transient failures (network, provider errors), the job is scheduled
        for retry with exponential backoff instead of being marked failed.
        Permanent failures (parsing, unsupported media) are marked failed immediately.
        """
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
            await self._retry.record_permanent_failure(
                job,
                "processing_profile_missing",
                "profile_or_generation_missing",
            )
            return
        if profile_error is not None:
            await self._retry.record_permanent_failure(
                job,
                profile_error,
                "profile_resolution_failed",
            )
            return
        assert generation is not None
        assert profile is not None
        assert chunker is not None
        try:
            await self._process_version(
                job, version, generation, profile, chunker, extracted_text, ner_complete
            )
        except Exception as error:
            error_category = self._retry.classify_error(error)
            if error_category == "permanent":
                error_code = getattr(error, "error_code", str(type(error).__name__))
                await self._retry.record_permanent_failure(
                    job,
                    error_code,
                    "permanent_processing_failure",
                )
            else:
                job_record = await self._jobs.get(job_id, job.tenant_id)
                attempt_count = job_record.attempt_count if job_record else 0
                await self._retry.record_transient_failure(
                    job,
                    attempt_count,
                    error,
                )

    async def _process_version(
        self,
        job: ProcessingJob,
        version: ProcessingDocumentVersion,
        generation: IndexGeneration,
        profile: ResolvedIngestionProfile,
        chunker: DocumentChunker,
        extracted_text: str | None,
        ner_complete: bool,
    ) -> None:
        """Process a single version through parsing, NER, chunking, and embedding."""
        ig_id: UUID | None = None
        if extracted_text is None:
            started_at = perf_counter()
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
                INGESTION_STAGE_DURATION.labels(stage="parsing", outcome="error").observe(
                    perf_counter() - started_at
                )
                await self._fail(job.job_id, version.document_version_id, "document_parsing_failed")
                return
            INGESTION_STAGE_DURATION.labels(stage="parsing", outcome="success").observe(
                perf_counter() - started_at
            )
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
            started_at = perf_counter()
            try:
                ner = self._ner_recognizers.create(profile.ner)
                ner_result = ner.recognize(extracted_text)
            except (NerError, ValueError):
                INGESTION_STAGE_DURATION.labels(stage="ner", outcome="error").observe(
                    perf_counter() - started_at
                )
                await self._fail(job.job_id, version.document_version_id, "ner_failed")
                return
            INGESTION_STAGE_DURATION.labels(stage="ner", outcome="success").observe(
                perf_counter() - started_at
            )
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
            started_at = perf_counter()
            ig_id = job.index_generation_id
            assert ig_id is not None
            try:
                chunks = chunker.chunk(extracted_text)
                async with self._transactions.begin():
                    current_generation = await self._index_generations.get(ig_id, version.tenant_id)
                    if (
                        current_generation is not None
                        and current_generation.chunking_completed_at is None
                    ):
                        await self._chunks.create_many(
                            CreateChunks(
                                document_version_id=version.document_version_id,
                                index_generation_id=ig_id,
                                tenant_id=version.tenant_id,
                                language=language,
                                chunks=chunks,
                            )
                        )
                        await self._index_generations.mark_chunking_complete(
                            ig_id, datetime.now(UTC)
                        )
            except Exception:
                INGESTION_STAGE_DURATION.labels(stage="chunking", outcome="error").observe(
                    perf_counter() - started_at
                )
                raise
            INGESTION_STAGE_DURATION.labels(stage="chunking", outcome="success").observe(
                perf_counter() - started_at
            )
        if generation.embedding_completed_at is None:
            started_at = perf_counter()
            ig_id = job.index_generation_id
            assert ig_id is not None
            async with self._transactions.begin():
                chunks_to_embed = await self._chunks.list_for_embedding(ig_id, version.tenant_id)
            try:
                embeddings = await self._embed_chunks(chunks_to_embed, profile.embedding)
            except (EmbeddingError, ValueError) as error:
                INGESTION_STAGE_DURATION.labels(stage="embedding", outcome="error").observe(
                    perf_counter() - started_at
                )
                logger.warning(
                    "Embedding stage failed",
                    extra={
                        "operation": "ingestion",
                        "stage": "embedding",
                        "outcome": "error",
                        "job_id": str(job.job_id),
                        "error_code": "embedding_failed",
                        "provider": profile.embedding.provider,
                        "capability": "embedding",
                        "duration_ms": round((perf_counter() - started_at) * 1000),
                    },
                )
                job_record = await self._jobs.get(job.job_id, job.tenant_id)
                attempt_count = job_record.attempt_count if job_record else 0
                await self._retry.record_transient_failure(
                    job,
                    attempt_count,
                    error,
                )
                return
            indexing_started_at = perf_counter()
            try:
                async with self._transactions.begin():
                    current_generation = await self._index_generations.get(ig_id, version.tenant_id)
                    if (
                        current_generation is not None
                        and current_generation.embedding_completed_at is None
                    ):
                        await self._chunk_embeddings.create_many(
                            CreateChunkEmbeddings(profile.embedding_profile_id, embeddings)
                        )
                        await self._index_generations.mark_embedding_complete(
                            ig_id, datetime.now(UTC)
                        )
            except Exception:
                INGESTION_STAGE_DURATION.labels(stage="indexing", outcome="error").observe(
                    perf_counter() - indexing_started_at
                )
                raise
            INGESTION_STAGE_DURATION.labels(stage="indexing", outcome="success").observe(
                perf_counter() - indexing_started_at
            )
            INGESTION_STAGE_DURATION.labels(stage="embedding", outcome="success").observe(
                perf_counter() - started_at
            )
        assert ig_id is not None, "index generation must exist after chunking stage"
        await self._complete(job.job_id, version.document_version_id, ig_id)

    async def _embed_chunks(
        self,
        chunks: tuple[ChunkForEmbedding, ...],
        configuration: EmbeddingConfiguration,
    ) -> tuple[ChunkEmbedding, ...]:
        """Generate stable profile-bound vectors in bounded provider batches.

        Raises EmbeddingError if any batch fails — the caller is responsible for
        retry classification. Partial success is not supported; either all chunks
        are embedded or the stage is retried.
        """
        embedder = self._embedders.create(configuration)
        result: list[ChunkEmbedding] = []
        for offset in range(0, len(chunks), configuration.batch_size):
            batch = chunks[offset : offset + configuration.batch_size]
            vectors = await embedder.embed(tuple(chunk.text for chunk in batch), configuration)
            if len(vectors) != len(batch):
                raise EmbeddingError("vector_count_mismatch")
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
        INGESTION_JOB_EVENTS.labels(outcome="failed").inc()
        INGESTION_TERMINAL_FAILURES.labels(error_code=error_code).inc()

    async def _complete(self, job_id: UUID, version_id: UUID, index_generation_id: UUID) -> None:
        """Atomically finish processing without activating the ready version."""
        ig_id = index_generation_id
        assert ig_id is not None
        async with self._transactions.begin():
            await self._document_versions.mark_ready(version_id)
            await self._index_generations.mark_ready(ig_id)
            await self._jobs.mark_ready(job_id, datetime.now(UTC))
        INGESTION_JOB_EVENTS.labels(outcome="ready").inc()
        INGESTION_WORKER_LAST_SUCCESS.set(time())
