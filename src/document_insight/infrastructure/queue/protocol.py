"""Protocol for publishing durable processing jobs."""

from typing import Protocol
from datetime import UTC, datetime
from uuid import UUID


class ProcessingQueue(Protocol):
    """Publish durable processing-job identifiers to asynchronous workers."""

    async def enqueue_ingestion(self, job_id: UUID, correlation_id: UUID) -> None:
        """Publish one ingestion job without carrying document content in the message."""

    async def re_enqueue_for_retry(
        self, job_id: UUID, correlation_id: UUID, next_retry_at: datetime
    ) -> None:
        """Re-enqueue a job that failed transiently and is scheduled for retry."""
