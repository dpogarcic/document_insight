"""Read durable processing-job state for operational monitoring."""

from datetime import datetime
from typing import Protocol

from document_insight.application.jobs.models import ProcessingJobMetricsSnapshot


class ProcessingJobMetricsRepository(Protocol):
    """Persistence capability required for an aggregate job monitoring read."""

    async def get_metrics_snapshot(self, now: datetime) -> ProcessingJobMetricsSnapshot:
        """Return one content-free aggregate processing-job snapshot."""


class ProcessingJobMonitoringService:
    """Read aggregate job state without exposing individual jobs or tenant data."""

    def __init__(self, jobs: ProcessingJobMetricsRepository) -> None:
        self._jobs = jobs

    async def snapshot(self, now: datetime) -> ProcessingJobMetricsSnapshot:
        """Return the current durable-job operational snapshot for one metric scrape."""
        return await self._jobs.get_metrics_snapshot(now)
