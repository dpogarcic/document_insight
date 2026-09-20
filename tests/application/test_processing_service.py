"""Focused tests for durable parsing checkpoints and failure classification."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from document_insight.application.ingestion.models import DocumentMediaType
from document_insight.application.jobs.models import ProcessingJob
from document_insight.application.processing.exceptions import ParsingError
from document_insight.application.processing.models import ParsedDocument
from document_insight.application.processing.service import ProcessingService
from document_insight.infrastructure.document_version.protocol import ProcessingDocumentVersion
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
    created: list[CreateExtractedDocument] = field(default_factory=list)

    async def exists(self, _: UUID) -> bool:
        return self.existing

    async def create(self, command: CreateExtractedDocument) -> None:
        self.created.append(command)
        self.existing = True


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
) -> tuple[ProcessingService, FakeJobs, FakeVersions, FakeExtractedDocuments, FakeParser]:
    """Build an isolated processing service and observable collaborator fakes."""
    job = ProcessingJob(uuid4(), uuid4(), uuid4(), uuid4())
    versions = FakeVersions(
        ProcessingDocumentVersion(job.document_version_id, job.tenant_id, "object-key", media_type)
    )
    jobs = FakeJobs(job)
    documents = FakeExtractedDocuments(existing=extracted)
    parser = FakeParser(parser_error)
    return (
        ProcessingService(
            jobs,
            versions,
            documents,
            FakeStorage(error=storage_error),
            pdf_parser=parser,
            image_parser=parser,
            transactions=FakeTransactions(),
        ),
        jobs,
        versions,
        documents,
        parser,
    )


@pytest.mark.anyio
async def test_processing_persists_one_version_scoped_parsing_checkpoint() -> None:
    """A claimed PDF moves to processing and writes one immutable extraction result."""
    service, jobs, versions, documents, parser = service_for()

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert versions.processing == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.created[0].parsed.text == "parsed text"
    assert parser.calls == 1


@pytest.mark.anyio
async def test_processing_skips_completed_parsing_checkpoint() -> None:
    """Re-delivery never reparses or duplicates a completed version result."""
    service, jobs, _, documents, parser = service_for(extracted=True)

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert documents.created == []
    assert parser.calls == 0


@pytest.mark.anyio
async def test_parsing_failure_marks_job_and_version_failed() -> None:
    """Malformed input exposes no parser detail and reaches a durable terminal state."""
    service, jobs, versions, documents, _ = service_for(parser_error=ParsingError())

    await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == [(jobs.job.job_id, "document_parsing_failed")]  # type: ignore[union-attr]
    assert versions.failed == [jobs.job.document_version_id]  # type: ignore[union-attr]
    assert documents.created == []


@pytest.mark.anyio
async def test_storage_failure_propagates_for_queue_retry() -> None:
    """Transient storage failures leave durable state retryable for RQ."""
    service, jobs, versions, documents, _ = service_for(storage_error=OSError())

    with pytest.raises(OSError):
        await service.process(jobs.job.job_id)  # type: ignore[union-attr]

    assert jobs.failures == []
    assert versions.failed == []
    assert documents.created == []
