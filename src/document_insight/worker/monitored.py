"""RQ worker that publishes its existing Redis heartbeat to Prometheus."""

from time import time

from redis.client import Pipeline
from rq import Worker

from document_insight.infrastructure.observability.processing_job_metrics import (
    INGESTION_WORKER_LAST_HEARTBEAT,
)


class MonitoredWorker(Worker):
    """Report idle and busy worker liveness without relying on completed jobs."""

    @property
    def dequeue_timeout(self) -> int:
        """Wake regularly enough for an idle worker to refresh its heartbeat."""
        return 15

    def heartbeat(self, timeout: int | None = None, pipeline: Pipeline | None = None) -> None:
        """Publish a heartbeat after RQ successfully updates Redis."""
        super().heartbeat(timeout, pipeline)
        INGESTION_WORKER_LAST_HEARTBEAT.set(time())
