"""Redis Queue adapter for durable ingestion jobs."""

import asyncio
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

from document_insight.application.ingestion.exceptions import QueueUnavailableError
from document_insight.infrastructure.queue.protocol import ProcessingQueue

_INGESTION_WORKER_FUNCTION = "document_insight.worker.ingestion.process_ingestion_job"


class RqProcessingQueue(ProcessingQueue):
    """Publish lightweight ingestion work references through Redis Queue."""

    def __init__(self, redis_url: str, queue_name: str) -> None:
        self._connection = Redis.from_url(redis_url)
        self._queue = Queue(name=queue_name, connection=self._connection)

    async def enqueue_ingestion(self, job_id: UUID, correlation_id: UUID) -> None:
        """Enqueue only durable IDs; originals remain in object storage."""
        try:
            await asyncio.to_thread(
                self._queue.enqueue,
                _INGESTION_WORKER_FUNCTION,
                str(job_id),
                str(correlation_id),
                job_id=str(job_id),
                description=f"Process ingestion job {job_id}",
                result_ttl=0,
            )
        except (OSError, RedisError) as error:
            raise QueueUnavailableError from error
