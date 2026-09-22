"""Unit tests for periodic durable processing-job recovery."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from document_insight.application.ingestion.exceptions import QueueUnavailableError
from document_insight.application.jobs.models import RequeueJob
from document_insight.application.processing.reconciliation import ProcessingJobReconciler
from document_insight.application.processing.retry import RetryConfig


@dataclass
class FakeJobs:
    candidates: tuple[RequeueJob, ...]
    exhausted_versions: tuple[UUID, ...] = ()
    prepared: list[UUID] = field(default_factory=list)
    enqueued: list[UUID] = field(default_factory=list)

    async def fail_stale_exhausted(self, *_: object) -> tuple[UUID, ...]:
        return self.exhausted_versions

    async def list_requeue_candidates(self, *_: object) -> tuple[RequeueJob, ...]:
        return self.candidates

    async def prepare_for_requeue(self, job_id: UUID, *_: object) -> RequeueJob | None:
        self.prepared.append(job_id)
        return next(
            (candidate for candidate in self.candidates if candidate.job_id == job_id), None
        )

    async def mark_enqueued(self, job_id: UUID, _: datetime) -> None:
        self.enqueued.append(job_id)


@dataclass
class FakeVersions:
    failed: list[UUID] = field(default_factory=list)

    async def mark_failed(self, version_id: UUID) -> None:
        self.failed.append(version_id)


@dataclass
class FakeQueue:
    unavailable: bool = False
    published: list[tuple[UUID, UUID]] = field(default_factory=list)

    async def enqueue_ingestion(self, job_id: UUID, correlation_id: UUID) -> None:
        if self.unavailable:
            raise QueueUnavailableError
        self.published.append((job_id, correlation_id))


class FakeTransactions:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


@pytest.mark.anyio
async def test_reconciler_republishes_recoverable_work_and_marks_exhausted_versions_failed() -> (
    None
):
    """Recovery uses durable state and leaves terminal version state consistent."""
    job = RequeueJob(uuid4(), uuid4(), uuid4())
    exhausted_version = uuid4()
    jobs = FakeJobs((job,), (exhausted_version,))
    versions = FakeVersions()
    queue = FakeQueue()
    reconciler = ProcessingJobReconciler(
        jobs,  # type: ignore[arg-type]
        versions,  # type: ignore[arg-type]
        queue,
        FakeTransactions(),
        RetryConfig(stale_threshold_minutes=10),
    )

    result = await reconciler.reconcile(datetime(2026, 9, 22, tzinfo=UTC))

    assert result.requeued_count == 1
    assert result.exhausted_count == 1
    assert jobs.prepared == [job.job_id]
    assert queue.published == [(job.job_id, job.correlation_id)]
    assert jobs.enqueued == [job.job_id]
    assert versions.failed == [exhausted_version]


@pytest.mark.anyio
async def test_reconciler_leaves_job_durable_when_queue_is_unavailable() -> None:
    """A failed publication remains eligible for the next periodic reconciliation pass."""
    job = RequeueJob(uuid4(), uuid4(), uuid4())
    jobs = FakeJobs((job,))
    queue = FakeQueue(unavailable=True)
    reconciler = ProcessingJobReconciler(
        jobs,  # type: ignore[arg-type]
        FakeVersions(),  # type: ignore[arg-type]
        queue,
        FakeTransactions(),
    )

    result = await reconciler.reconcile(datetime.now(UTC) - timedelta(minutes=1))

    assert result.requeued_count == 0
    assert queue.published == []
    assert jobs.enqueued == []
