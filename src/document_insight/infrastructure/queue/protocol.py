"""Protocol for publishing durable processing jobs."""

from typing import Protocol
from uuid import UUID


class ProcessingQueue(Protocol):
    """Publish durable processing-job identifiers to asynchronous workers."""

    async def enqueue_ingestion(self, job_id: UUID, correlation_id: UUID) -> None:
        """Publish one ingestion job without carrying document content in the message."""
