"""Periodic durable-job recovery for the ingestion worker fleet."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from document_insight.application.ingestion.exceptions import QueueUnavailableError
from document_insight.application.processing.retry import RetryConfig
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.queue.protocol import ProcessingQueue

logger = logging.getLogger(__name__)

_RECOVERY_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Observable outcome of one bounded durable-job recovery pass."""

    requeued_count: int
    exhausted_count: int


class ProcessingJobReconciler:
    """Republish orphaned work and recover only retryable transient failures."""

    def __init__(
        self,
        jobs: JobRepository,
        document_versions: DocumentVersionRepository,
        queue: ProcessingQueue,
        transactions: TransactionManager,
        retry_config: RetryConfig | None = None,
        batch_size: int = _RECOVERY_BATCH_SIZE,
    ) -> None:
        self._jobs = jobs
        self._document_versions = document_versions
        self._queue = queue
        self._transactions = transactions
        self._retry_config = retry_config or RetryConfig()
        self._batch_size = batch_size

    async def reconcile(self, now: datetime | None = None) -> ReconciliationResult:
        """Run one bounded recovery pass using PostgreSQL as the source of truth."""
        current_time = now or datetime.now(UTC)
        stale_before = current_time - timedelta(minutes=self._retry_config.stale_threshold_minutes)
        async with self._transactions.begin():
            exhausted_versions = await self._jobs.fail_stale_exhausted(
                current_time, stale_before, self._retry_config.max_attempts
            )
            for version_id in exhausted_versions:
                await self._document_versions.mark_failed(version_id)
            candidates = await self._jobs.list_requeue_candidates(
                current_time,
                stale_before,
                self._retry_config.max_attempts,
                self._batch_size,
            )

        requeued_count = 0
        for candidate in candidates:
            async with self._transactions.begin():
                recovered = await self._jobs.prepare_for_requeue(
                    candidate.job_id,
                    current_time,
                    stale_before,
                    self._retry_config.max_attempts,
                )
            if recovered is None:
                continue
            try:
                await self._queue.enqueue_ingestion(recovered.job_id, recovered.correlation_id)
            except QueueUnavailableError:
                logger.warning(
                    "processing job recovery queue publication deferred",
                    extra={"job_id": str(recovered.job_id)},
                )
                continue
            async with self._transactions.begin():
                await self._jobs.mark_enqueued(recovered.job_id, current_time)
            requeued_count += 1

        if requeued_count or exhausted_versions:
            logger.info(
                "processing job reconciliation completed",
                extra={
                    "requeued_count": requeued_count,
                    "exhausted_count": len(exhausted_versions),
                },
            )
        return ReconciliationResult(requeued_count, len(exhausted_versions))
