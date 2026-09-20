"""Focused tests for durable parsing checkpoints and failure classification."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.jobs.models import ProcessingJob
from document_insight.application.processing.exceptions import NerError, ParsingError
from document_insight.application.processing.models import (
    CanonicalEntity,
    DocumentLanguage,
    EntityLabel,
    NamedEntity,
    NerResult,
    ParsedDocument,
)
from document_insight.application.processing.service import ProcessingService
from document_insight.infrastructure.document_version.protocol import ProcessingDocumentVersion
from document_insight.infrastructure.entity.protocol import CreateEntities
from document_insight.infrastructure.extracted_document.protocol import CreateExtractedDocument


@dataclass
class FakeJobs:
    job: ProcessingJob | None
    failures: list[tuple[UUID, str]] = field(default_factory=list)

    async def claim(self, _: UUID, __: datetime) -> ProcessingJob | None:
        return self.job

    async def fail(self, job_id: UUID, error_code: str, _: datetime) -> None:
        self.failures.append((job_id, error_code))


@dataclass
class FakeVersions:
    version: ProcessingDocumentVersion
    processing: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)

    async def mark_processing(self, version_id: UUID) -> None:
        self.processing.append(version_id)

    async def mark_failed(self, version_id: UUID) -> None:
        self.failed.append(version_id)

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


@dataclass
class FakeEntities:
    created: list[CreateEntities] = field(default_factory=list)

    async def create_many(self, command: CreateEntities) -> None:
        self.created.append(command)


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
    ner_error: Exception | None = None,
) -> tuple[
    ProcessingService,
    FakeJobs,
    FakeVersions,
    FakeExtractedDocuments,
    FakeParser,
    FakeEntities,
    FakeNer,
]:
    """Build an isolated processing service and observable collaborator fakes."""
    job = ProcessingJob(uuid4(), uuid4(), uuid4(), uuid4())
    versions = FakeVersions(
        ProcessingDocumentVersion(job.document_version_id, job.tenant_id, "object-key", media_type)
    )
    jobs = FakeJobs(job)
    documents = FakeExtractedDocuments(existing=extracted, ner_complete=ner_complete)
    parser = FakeParser(parser_error)
    entities = FakeEntities()
    ner = FakeNer(ner_error)
    return (
        ProcessingService(
            jobs,
            versions,
            documents,
            entities,
            FakeStorage(error=storage_error),
            pdf_parser=parser,
            image_parser=parser,
            ner=ner,
            transactions=FakeTransactions(),
        ),
        jobs,
        versions,
        documents,
        parser,
        entities,
        ner,
    )


@pytest.mark.anyio
async def test_processing_persists_one_version_scoped_parsing_checkpoint() -> None:
    """A claimed PDF moves to processing and writes one immutable extraction result."""
    service, jobs, versions, documents, parser, entities, ner = service_for()

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
    assert ner.calls == ["parsed text"]


@pytest.mark.anyio
async def test_processing_skips_completed_parsing_checkpoint() -> None:
    """Re-delivery never reparses or duplicates a completed version result."""
    service, jobs, _, documents, parser, entities, ner = service_for(
        extracted=True, ner_complete=True
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert documents.created == []
    assert parser.calls == 0
    assert entities.created == []
    assert ner.calls == []


@pytest.mark.anyio
async def test_parsing_failure_marks_job_and_version_failed() -> None:
    """Malformed input exposes no parser detail and reaches a durable terminal state."""
    service, jobs, versions, documents, _, _, _ = service_for(parser_error=ParsingError())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == [(jobs.job.job_id, "document_parsing_failed")]  # type: ignore[union-attr]
    assert versions.failed == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.created == []


@pytest.mark.anyio
async def test_storage_failure_propagates_for_queue_retry() -> None:
    """Transient storage failures leave durable state retryable for RQ."""
    service, jobs, versions, documents, _, _, _ = service_for(storage_error=OSError())

    with pytest.raises(OSError):
        await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == []
    assert versions.failed == []
    assert documents.created == []


@pytest.mark.anyio
async def test_existing_parse_resumes_with_ner_and_checkpoints_empty_results() -> None:
    """NER resumes after parsing and completion does not depend on finding entities."""
    service, jobs, _, documents, parser, entities, ner = service_for(extracted=True)
    ner.recognize = lambda text: NerResult(DocumentLanguage.CROATIAN, "fake", "fake-hr", ())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert parser.calls == 0
    assert entities.created[0].entities == ()
    assert documents.ner_complete is True


@pytest.mark.anyio
async def test_ner_result_is_deduplicated_to_document_version_metadata() -> None:
    """Repeated mentions persist once with a count and the first display spelling."""
    service, jobs, _, _, _, entities, ner = service_for(extracted=True)
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
    service, jobs, versions, documents, _, entities, _ = service_for(
        extracted=True, ner_error=NerError()
    )

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == [(jobs.job.job_id, "ner_failed")]  # type: ignore[union-attr]
    assert versions.failed == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.ner_complete is False
    assert entities.created == []
