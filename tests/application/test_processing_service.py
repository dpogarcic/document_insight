"""Focused tests for durable parsing checkpoints and failure classification."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from document_insight.application.configuration.models import (
    ChunkingConfiguration,
    EmbeddingConfiguration,
    NerConfiguration,
    ResolvedIngestionProfile,
)
from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.jobs.models import JobRecord, JobStatus, ProcessingJob
from document_insight.application.processing.exceptions import (
    EmbeddingError,
    NerError,
    ParsingError,
)
from document_insight.application.processing.models import (
    CanonicalEntity,
    DocumentLanguage,
    EntityLabel,
    NamedEntity,
    NerResult,
    ParsedDocument,
)
from document_insight.application.processing.service import ProcessingService
from document_insight.infrastructure.chunk.protocol import ChunkForEmbedding
from document_insight.infrastructure.chunk_embedding.protocol import CreateChunkEmbeddings
from document_insight.infrastructure.document_version.protocol import ProcessingDocumentVersion
from document_insight.infrastructure.entity.protocol import CreateEntities
from document_insight.infrastructure.extracted_document.protocol import CreateExtractedDocument
from document_insight.infrastructure.index_generation.protocol import IndexGeneration


@dataclass
class FakeJobs:
    job: ProcessingJob | None
    failures: list[tuple[UUID, str]] = field(default_factory=list)
    ready: list[UUID] = field(default_factory=list)
    attempts: dict[UUID, int] = field(default_factory=dict)

    async def claim(self, _: UUID, __: datetime) -> ProcessingJob | None:
        return self.job

    async def get(self, job_id: UUID, tenant_id: UUID) -> JobRecord | None:
        if self.job is None or self.job.job_id != job_id:
            return None
        return JobRecord(
            job_id=self.job.job_id,
            tenant_id=self.job.tenant_id,
            document_version_id=self.job.document_version_id,
            status=JobStatus.PROCESSING,
            attempt_count=self.attempts.get(job_id, 0),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            error_code=None,
        )

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        finished_at: datetime,
        error_category: str = "permanent",
        failure_reason: str | None = None,
    ) -> None:
        self.failures.append((job_id, error_code))

    async def mark_enqueued(self, job_id: UUID, enqueued_at: datetime) -> None:
        pass

    async def retry(
        self,
        job_id: UUID,
        attempt_count: int,
        next_retry_at: datetime,
        error_category: str = "transient",
    ) -> None:
        self.attempts[job_id] = attempt_count

    async def mark_ready(self, job_id: UUID, _: datetime) -> None:
        self.ready.append(job_id)


@dataclass
class FakeVersions:
    version: ProcessingDocumentVersion
    processing: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)
    ready: list[UUID] = field(default_factory=list)

    async def mark_processing(self, version_id: UUID) -> None:
        self.processing.append(version_id)

    async def mark_failed(self, version_id: UUID) -> None:
        self.failed.append(version_id)

    async def mark_ready(self, version_id: UUID) -> None:
        self.ready.append(version_id)

    async def get_for_processing(self, _: UUID, __: UUID) -> ProcessingDocumentVersion:
        return self.version


@dataclass
class FakeExtractedDocuments:
    existing: bool = False
    ner_complete: bool = False
    created: list[CreateExtractedDocument] = field(default_factory=list)
    ner_results: list[NerResult] = field(default_factory=list)

    async def exists(self, _: UUID) -> bool:
        return self.existing

    async def create(self, command: CreateExtractedDocument) -> None:
        self.created.append(command)
        self.existing = True

    async def get_text(self, _: UUID) -> str | None:
        return "already parsed" if self.existing else None

    async def ner_is_complete(self, _: UUID) -> bool:
        return self.ner_complete

    async def mark_ner_complete(self, _: UUID, result: NerResult, __: datetime) -> None:
        self.ner_results.append(result)
        self.ner_complete = True

    async def get_ner_metadata(self, _: UUID):
        from document_insight.infrastructure.extracted_document.protocol import NerMetadata

        return NerMetadata(DocumentLanguage.ENGLISH) if self.ner_complete else None


@dataclass
class FakeEntities:
    created: list[CreateEntities] = field(default_factory=list)

    async def create_many(self, command: CreateEntities) -> None:
        self.created.append(command)


@dataclass
class FakeChunks:
    created: list[object] = field(default_factory=list)
    embedding_chunk: ChunkForEmbedding = field(
        default_factory=lambda: ChunkForEmbedding(uuid4(), "chunk for embedding")
    )

    async def create_many(self, command: object) -> None:
        self.created.append(command)

    async def list_for_embedding(self, _: UUID, __: UUID) -> tuple[ChunkForEmbedding, ...]:
        return (self.embedding_chunk,)


@dataclass
class FakeChunkEmbeddings:
    created: list[CreateChunkEmbeddings] = field(default_factory=list)

    async def create_many(self, command: CreateChunkEmbeddings) -> None:
        self.created.append(command)


@dataclass
class FakeIndexGenerations:
    generation: IndexGeneration
    completed: list[UUID] = field(default_factory=list)
    ready: list[UUID] = field(default_factory=list)

    async def get(self, _: UUID, __: UUID) -> IndexGeneration:
        return self.generation

    async def mark_chunking_complete(self, generation_id: UUID, _: datetime) -> None:
        self.completed.append(generation_id)
        self.generation = IndexGeneration(
            self.generation.index_generation_id,
            self.generation.ingestion_profile_id,
            datetime.now(),
            self.generation.embedding_completed_at,
        )

    async def mark_embedding_complete(self, generation_id: UUID, _: datetime) -> None:
        self.completed.append(generation_id)
        self.generation = IndexGeneration(
            self.generation.index_generation_id,
            self.generation.ingestion_profile_id,
            self.generation.chunking_completed_at,
            datetime.now(),
        )

    async def mark_ready(self, generation_id: UUID) -> None:
        self.ready.append(generation_id)


class FakeChunker:
    def chunk(self, text: str):
        from document_insight.application.processing.models import DocumentChunk

        return (DocumentChunk(0, text, 0, len(text), 1),)


class FakeChunkerFactory:
    def create(self, _: ChunkingConfiguration) -> FakeChunker:
        return FakeChunker()


class FakeProfileResolver:
    def __init__(self, ingestion_profile_id: UUID) -> None:
        self._ingestion_profile_id = ingestion_profile_id

    async def resolve(self, _: UUID) -> ResolvedIngestionProfile:
        return ResolvedIngestionProfile(
            ingestion_profile_id=self._ingestion_profile_id,
            ner_profile_id=uuid4(),
            chunking_profile_id=uuid4(),
            lexical_profile_id=uuid4(),
            embedding_profile_id=uuid4(),
            ner=NerConfiguration(
                provider="fake", english_model="fake", croatian_model="fake", model_revision="1"
            ),
            chunking=ChunkingConfiguration(
                implementation="fake",
                implementation_revision="1",
                max_chars=1_000,
                overlap_chars=100,
            ),
            embedding=EmbeddingConfiguration(
                provider="fake",
                model="fake-embedding-model",
                configuration_revision="1",
                dimensions=2,
                normalize=True,
                batch_size=8,
            ),
        )

    version = "1"

    def chunk(self, text: str):
        from document_insight.application.processing.models import DocumentChunk

        return (DocumentChunk(0, text, 0, len(text), 1),)


@dataclass
class FakeNer:
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def recognize(self, text: str) -> NerResult:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        entity = NamedEntity("OpenAI", "openai", EntityLabel.ORG)
        return NerResult(DocumentLanguage.ENGLISH, "fake", "fake-ner", (entity,))


@dataclass
class FakeNerFactory:
    recognizer: FakeNer
    configurations: list[NerConfiguration] = field(default_factory=list)

    def create(self, configuration: NerConfiguration) -> FakeNer:
        self.configurations.append(configuration)
        return self.recognizer


@dataclass
class FakeEmbedder:
    error: Exception | None = None
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def embed(
        self, texts: tuple[str, ...], _: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return tuple((3.0, 4.0) for _ in texts)


@dataclass
class FakeEmbedderFactory:
    embedder: FakeEmbedder

    def create(self, _: EmbeddingConfiguration) -> FakeEmbedder:
        return self.embedder


@dataclass
class FakeStorage:
    content: bytes = b"pdf"
    error: Exception | None = None

    async def get(self, _: str) -> bytes:
        if self.error is not None:
            raise self.error
        return self.content


@dataclass
class FakeParser:
    error: Exception | None = None
    calls: int = 0

    def parse(self, _: bytes) -> ParsedDocument:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ParsedDocument("parsed text", 1, "fake", "1")


class FakeTransactions:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


def service_for(
    media_type: DocumentMediaType = DocumentMediaType.PDF,
    parser_error: Exception | None = None,
    storage_error: Exception | None = None,
    extracted: bool = False,
    ner_complete: bool = False,
    chunking_complete: bool = False,
    embedding_complete: bool = False,
    ner_error: Exception | None = None,
    embedding_error: Exception | None = None,
) -> tuple[
    ProcessingService,
    FakeJobs,
    FakeVersions,
    FakeExtractedDocuments,
    FakeParser,
    FakeEntities,
    FakeChunks,
    FakeNer,
    FakeChunkEmbeddings,
    FakeEmbedder,
]:
    """Build an isolated processing service and observable collaborator fakes."""
    job = ProcessingJob(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 0)
    versions = FakeVersions(
        ProcessingDocumentVersion(job.document_version_id, job.tenant_id, "object-key", media_type)
    )
    jobs = FakeJobs(job)
    documents = FakeExtractedDocuments(existing=extracted, ner_complete=ner_complete)
    parser = FakeParser(parser_error)
    entities = FakeEntities()
    chunks = FakeChunks()
    chunk_embeddings = FakeChunkEmbeddings()
    generations = FakeIndexGenerations(
        IndexGeneration(
            job.index_generation_id,
            job.ingestion_profile_id,
            datetime.now() if chunking_complete else None,
            datetime.now() if embedding_complete else None,
        )
    )
    ner = FakeNer(ner_error)
    embedder = FakeEmbedder(embedding_error)
    return (
        ProcessingService(
            jobs,
            versions,
            documents,
            entities,
            chunks,
            chunk_embeddings,
            generations,
            FakeProfileResolver(job.ingestion_profile_id),  # type: ignore[arg-type]
            FakeStorage(error=storage_error),
            pdf_parser=parser,
            image_parser=parser,
            ner_recognizers=FakeNerFactory(ner),
            chunkers=FakeChunkerFactory(),
            embedders=FakeEmbedderFactory(embedder),
            transactions=FakeTransactions(),
        ),
        jobs,
        versions,
        documents,
        parser,
        entities,
        chunks,
        ner,
        chunk_embeddings,
        embedder,
    )


@pytest.mark.anyio
async def test_processing_persists_one_version_scoped_parsing_checkpoint() -> None:
    """A claimed PDF moves to processing and writes one immutable extraction result."""
    service, jobs, versions, documents, parser, entities, chunks, ner, embeddings, embedder = (
        service_for()
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert versions.processing == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.created[0].parsed.text == "parsed text"
    assert parser.calls == 1
    assert entities.created == [
        CreateEntities(
            document_version_id=jobs.job.document_version_id,  # type: ignore[union-attr]
            tenant_id=jobs.job.tenant_id,  # type: ignore[union-attr]
            language=DocumentLanguage.ENGLISH,
            ner_provider="fake",
            ner_model="fake-ner",
            entities=(CanonicalEntity("OpenAI", "openai", EntityLabel.ORG, 1),),
        )
    ]
    assert len(chunks.created) == 1
    assert embedder.calls == [("chunk for embedding",)]
    assert len(embeddings.created) == 1
    assert embeddings.created[0].embeddings[0].values == (3.0, 4.0)
    assert jobs.ready == [jobs.job.job_id]  # type: ignore[union-attr]
    assert versions.ready == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert ner.calls == ["parsed text"]


@pytest.mark.anyio
async def test_processing_skips_completed_parsing_checkpoint() -> None:
    """Re-delivery never reparses or duplicates a completed version result."""
    service, jobs, _, documents, parser, entities, chunks, ner, _, embedder = service_for(
        extracted=True, ner_complete=True, chunking_complete=True
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert documents.created == []
    assert parser.calls == 0
    assert entities.created == []
    assert chunks.created == []
    assert ner.calls == []
    assert embedder.calls == [("chunk for embedding",)]


@pytest.mark.anyio
async def test_parsing_failure_marks_job_and_version_failed() -> None:
    """Malformed input exposes no parser detail and reaches a durable terminal state."""
    service, jobs, versions, documents, _, _, _, _, _, _ = service_for(parser_error=ParsingError())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == [(jobs.job.job_id, "document_parsing_failed")]  # type: ignore[union-attr]
    assert versions.failed == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.created == []


@pytest.mark.anyio
async def test_storage_failure_propagates_for_queue_retry() -> None:
    """Transient storage failures are classified as transient and scheduled for retry."""
    service, jobs, versions, documents, _, _, _, _, _, _ = service_for(storage_error=OSError())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    # OSError from storage is now classified as transient, not propagated
    assert jobs.failures == []
    assert versions.failed == []
    assert documents.created == []


@pytest.mark.anyio
async def test_existing_parse_resumes_with_ner_and_checkpoints_empty_results() -> None:
    """NER resumes after parsing and completion does not depend on finding entities."""
    service, jobs, _, documents, parser, entities, _, ner, _, _ = service_for(extracted=True)
    ner.recognize = lambda text: NerResult(DocumentLanguage.CROATIAN, "fake", "fake-hr", ())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert parser.calls == 0
    assert entities.created[0].entities == ()
    assert documents.ner_complete is True


@pytest.mark.anyio
async def test_ner_result_is_deduplicated_to_document_version_metadata() -> None:
    """Repeated mentions persist once with a count and the first display spelling."""
    service, jobs, _, _, _, entities, _, ner, _, _ = service_for(extracted=True)
    ner.recognize = lambda text: NerResult(
        DocumentLanguage.ENGLISH,
        "fake",
        "fake-ner",
        (
            NamedEntity("OpenAI", "openai", EntityLabel.ORG),
            NamedEntity("OPENAI", "openai", EntityLabel.ORG),
            NamedEntity("OpenAI", "openai", EntityLabel.PRODUCT),
            NamedEntity("Briefs Academy", "briefs academy", EntityLabel.ORG),
        ),
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert entities.created[0].entities == (
        CanonicalEntity("OpenAI", "openai", EntityLabel.ORG, 2),
        CanonicalEntity("OpenAI", "openai", EntityLabel.PRODUCT, 1),
        CanonicalEntity("Briefs Academy", "briefs academy", EntityLabel.ORG, 1),
    )


@pytest.mark.anyio
async def test_ner_failure_marks_job_and_version_failed() -> None:
    """Provider failures become safe durable state without storing raw error details."""
    service, jobs, versions, documents, _, entities, _, _, _, _ = service_for(
        extracted=True, ner_error=NerError()
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == [(jobs.job.job_id, "ner_failed")]  # type: ignore[union-attr]
    assert versions.failed == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.ner_complete is False
    assert entities.created == []


@pytest.mark.anyio
async def test_embedding_failure_is_transient_and_scheduled_for_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Embedding provider failures are transient and scheduled for retry."""
    service, jobs, versions, _, _, _, _, _, embeddings, embedder = service_for(
        embedding_error=EmbeddingError("provider_rejected_http_400")
    )
    caplog.set_level(logging.WARNING, logger="document_insight.application.processing.retry")

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert embedder.calls == [("chunk for embedding",)]
    assert embeddings.created == []
    # Embedding failures are transient — job is scheduled for retry, not marked failed
    assert jobs.failures == []
    assert versions.failed == []
    assert "stalled for" in caplog.text
    assert "embedding_failed" in caplog.text or "Embedding stage failed" in caplog.text
