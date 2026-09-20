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
