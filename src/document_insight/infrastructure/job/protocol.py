"""Processing-job repository protocol and creation command."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from document_insight.application.jobs.models import (
    JobRecord,
    ProcessingJob,
    ProcessingJobMetricsSnapshot,
    RequeueJob,
)


@dataclass(frozen=True, slots=True)
class CreateJob:
    """Server-generated fields for one durable processing job."""

    job_id: UUID
    tenant_id: UUID
    document_version_id: UUID
    idempotency_key: UUID
    correlation_id: UUID
    created_by: UUID
    ingestion_profile_id: UUID
    index_generation_id: UUID


class JobRepository(Protocol):
    """Persistence operations owned by processing jobs."""

    async def create(self, command: CreateJob) -> None:
        """Create one durable job in its initial queued state."""

    async def get(self, job_id: UUID, tenant_id: UUID) -> JobRecord | None:
        """Return one tenant-scoped job without loading related entities."""

    async def mark_enqueued(self, job_id: UUID, enqueued_at: datetime) -> None:
        """Record successful queue publication for an existing durable job."""

    async def claim(self, job_id: UUID, started_at: datetime) -> ProcessingJob | None:
        """Claim a queued or retried processing job and return worker-only data."""

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        finished_at: datetime,
        error_category: str = "permanent",
        failure_reason: str | None = None,
    ) -> None:
        """Persist a safe terminal processing failure."""

    async def mark_ready(self, job_id: UUID, finished_at: datetime) -> None:
        """Persist completion after every derived-data checkpoint succeeds."""

    async def retry(
        self,
        job_id: UUID,
        attempt_count: int,
        next_retry_at: datetime,
        error_category: str = "transient",
    ) -> None:
        """Schedule a transient failure for retry with exponential backoff.

        Updates the job to queuing state with retry timing metadata so the
        reconciliation process or a scheduled retry can resume it.
        """

    async def list_requeue_candidates(
        self, now: datetime, stale_before: datetime, max_attempts: int, limit: int
    ) -> tuple[RequeueJob, ...]:
        """Return a bounded set of durable jobs that may need queue recovery."""

    async def prepare_for_requeue(
        self, job_id: UUID, now: datetime, stale_before: datetime, max_attempts: int
    ) -> RequeueJob | None:
        """Atomically make one eligible job ready for another queue publication."""

    async def fail_stale_exhausted(
        self, now: datetime, stale_before: datetime, max_attempts: int
    ) -> tuple[UUID, ...]:
        """Fail stale in-progress jobs that have exhausted their retry budget."""

    async def get_metrics_snapshot(self, now: datetime) -> ProcessingJobMetricsSnapshot:
        """Return content-free aggregate state for operational metrics."""
