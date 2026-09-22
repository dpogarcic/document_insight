"""Processing-job models used by the application layer."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class JobStatus(StrEnum):
    """Authoritative processing lifecycle stored in PostgreSQL."""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingStage(StrEnum):
    """Ordered stages reserved for the version processing pipeline."""

    PARSING = "parsing"
    NER = "ner"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class JobRecord:
    """Job data loaded from persistence without related document projections."""

    job_id: UUID
    tenant_id: UUID
    document_version_id: UUID
    status: JobStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None
    error_category: str | None = None
    failure_reason: str | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    """Internal durable data used only by the processing worker."""

    job_id: UUID
    tenant_id: UUID
    document_version_id: UUID
    correlation_id: UUID
    ingestion_profile_id: UUID | None
    index_generation_id: UUID | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class Job:
    """Authorized processing state of one document-version job."""

    job_id: UUID
    document_id: UUID
    document_version_id: UUID
    status: JobStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None
