"""Processing-job repository protocol and creation command."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.jobs.models import JobRecord


@dataclass(frozen=True, slots=True)
class CreateJob:
    """Server-generated fields for one durable processing job."""

    job_id: UUID
    tenant_id: UUID
    document_version_id: UUID
    idempotency_key: UUID
    correlation_id: UUID
    created_by: UUID


class JobRepository(Protocol):
    """Persistence operations owned by processing jobs."""

    async def create(self, command: CreateJob) -> None:
        """Create one durable job in its initial queued state."""

    async def get(self, job_id: UUID, tenant_id: UUID) -> JobRecord | None:
        """Return one tenant-scoped job without loading related entities."""
