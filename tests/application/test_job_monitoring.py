"""Tests for durable processing-job operational monitoring."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from document_insight.application.jobs.models import JobStatus, ProcessingJobMetricsSnapshot
from document_insight.application.jobs.monitoring import ProcessingJobMonitoringService


@dataclass
class FakeJobs:
    result: ProcessingJobMetricsSnapshot
    received_now: datetime | None = None

    async def get_metrics_snapshot(self, now: datetime) -> ProcessingJobMetricsSnapshot:
        self.received_now = now
        return self.result


@pytest.mark.anyio
async def test_monitoring_reads_only_the_aggregate_durable_job_snapshot() -> None:
    """The monitoring service delegates aggregate state to the authoritative repository."""
    snapshot = ProcessingJobMetricsSnapshot(
        counts_by_status=((JobStatus.QUEUED, 3), (JobStatus.FAILED, 1)),
        oldest_queued_age_seconds=42.0,
        oldest_processing_age_seconds=3.0,
        retry_scheduled_count=2,
    )
    jobs = FakeJobs(snapshot)
    now = datetime(2026, 9, 22, tzinfo=UTC)

    result = await ProcessingJobMonitoringService(jobs).snapshot(now)

    assert result == snapshot
    assert jobs.received_now == now
