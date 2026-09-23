"""RQ transport for persisted evaluation run identifiers."""

import asyncio
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue


class RqEvaluationQueue:
    """Publish only durable run IDs to the private evaluation worker."""

    def __init__(self, redis_url: str, queue_name: str) -> None:
        self._queue = Queue(queue_name, connection=Redis.from_url(redis_url))

    async def enqueue(self, run_id: UUID) -> None:
        """Submit a run; PostgreSQL remains the source of truth on Redis failure."""
        try:
            await asyncio.to_thread(
                self._queue.enqueue,
                "document_insight.worker.evaluation.process_evaluation_run",
                str(run_id),
                job_id=f"evaluation-{run_id}",
                description=f"Evaluate run {run_id}",
                result_ttl=0,
            )
        except (OSError, RedisError) as error:
            raise RuntimeError("Evaluation queue is unavailable") from error
