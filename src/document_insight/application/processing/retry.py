"""Retry handling for the processing pipeline.

Implements exponential backoff with jitter for transient failures,
permanent failure classification, and max-attempts enforcement.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Protocol

from document_insight.application.jobs.models import ProcessingJob
from document_insight.application.processing.exceptions import (
    EmbeddingError,
    NerError,
    ParsingError,
    UnsupportedProcessingMediaTypeError,
)
from document_insight.infrastructure.job.protocol import JobRepository
from document_insight.infrastructure.observability.processing_job_metrics import (
    INGESTION_JOB_EVENTS,
    INGESTION_TERMINAL_FAILURES,
)
from document_insight.infrastructure.queue.protocol import ProcessingQueue

logger = logging.getLogger(__name__)

# Retry configuration constants
MAX_ATTEMPTS_DEFAULT = 5
BASE_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60
BACKOFF_MULTIPLIER = 2.0
JITTER_FACTOR = 0.25  # ±25%
STALE_THRESHOLD_MINUTES = 10


class RetryConfig:
    """Configuration for retry behavior.

    Defaults align with the retry design document.
    """

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS_DEFAULT,
        base_backoff_seconds: int = BASE_BACKOFF_SECONDS,
        max_backoff_seconds: int = MAX_BACKOFF_SECONDS,
        backoff_multiplier: float = BACKOFF_MULTIPLIER,
        jitter_factor: float = JITTER_FACTOR,
        stale_threshold_minutes: int = STALE_THRESHOLD_MINUTES,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.backoff_multiplier = backoff_multiplier
        self.jitter_factor = jitter_factor
        self.stale_threshold_minutes = stale_threshold_minutes

    def calculate_backoff(self, attempt: int) -> timedelta:
        """Calculate exponential backoff with jitter for the given attempt.

        Formula: min(MAX_BACKOFF, BASE_BACKOFF * MULTIPLIER^attempt) + jitter
        Jitter is a random value in [-JITTER_FACTOR, +JITTER_FACTOR] of the backoff.
        """
        base = min(
            self.max_backoff_seconds,
            int(self.base_backoff_seconds * (self.backoff_multiplier**attempt)),
        )
        jitter_range = base * self.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)
        return timedelta(seconds=max(0, base + jitter))

    def is_retryable(self, attempt_count: int) -> bool:
        """Check if the job has remaining retry attempts."""
        return attempt_count < self.max_attempts

    def is_stale(self, updated_at: datetime) -> bool:
        """Check if a processing job has exceeded the stale threshold."""
        threshold = timedelta(minutes=self.stale_threshold_minutes)
        return datetime.now(UTC) - updated_at > threshold


class ProcessingJobRetry(Protocol):
    """Retry coordination for processing jobs."""

    async def record_transient_failure(
        self,
        job: ProcessingJob,
        attempt_count: int,
        error: Exception,
    ) -> None:
        """Record a transient failure and schedule retry if attempts remain."""

    async def record_permanent_failure(
        self,
        job: ProcessingJob,
        error_code: str,
        reason: str,
    ) -> None:
        """Record a permanent failure that should not be retried."""


class RetryCoordinator:
    """Coordinates retry behavior for processing jobs.

    Classifies failures as transient or permanent, calculates backoff,
    records state on the job, and re-enqueues in the queue for retry.
    """

    def __init__(
        self,
        jobs: JobRepository,
        config: RetryConfig | None = None,
        queue: ProcessingQueue | None = None,
    ) -> None:
        self._jobs = jobs
        self._config = config or RetryConfig()
        self._queue = queue

    def classify_error(self, error: Exception) -> str:
        """Classify an error as 'transient' or 'permanent'."""
        if isinstance(error, (ParsingError, UnsupportedProcessingMediaTypeError)):
            return "permanent"
        if isinstance(error, NerError):
            # NER failures are typically transient (model load issues, timeouts)
            return "transient"
        if isinstance(error, EmbeddingError):
            # Embedding failures are transient (network, provider issues)
            return "transient"
        # Default: assume transient for unknown errors (conservative)
        return "transient"

    async def record_transient_failure(
        self,
        job: ProcessingJob,
        attempt_count: int,
        error: Exception,
    ) -> bool:
        """Record a transient failure and schedule retry if attempts remains.

        Returns True if the job was scheduled for retry, False if max attempts reached.
        """
        if not self._config.is_retryable(attempt_count):
            # Max attempts reached - convert to permanent failure
            await self._jobs.fail(
                job.job_id,
                "max_attempts_reached",
                datetime.now(UTC),
                error_category="permanent",
                failure_reason="max_attempts_reached",
            )
            INGESTION_JOB_EVENTS.labels(outcome="failed").inc()
            INGESTION_TERMINAL_FAILURES.labels(error_code="max_attempts_reached").inc()
            logger.error(
                "processing job %s marked failed: max_attempts_reached "
                "(attempt %d/%d, category permanent)",
                job.job_id,
                attempt_count,
                self._config.max_attempts,
                extra={
                    "job_id": str(job.job_id),
                    "attempt_count": attempt_count,
                    "max_attempts": self._config.max_attempts,
                    "error_category": "permanent",
                    "failure_reason": "max_attempts_reached",
                },
            )
            return False

        backoff = self._config.calculate_backoff(attempt_count)
        next_retry_at = datetime.now(UTC) + backoff

        await self._jobs.retry(
            job.job_id,
            attempt_count + 1,
            next_retry_at,
            error_category="transient",
        )
        INGESTION_JOB_EVENTS.labels(outcome="retry_scheduled").inc()

        # Re-enqueue in the queue so the worker picks it up after backoff
        if self._queue is not None:
            try:
                await self._queue.re_enqueue_for_retry(
                    job.job_id, job.correlation_id, next_retry_at
                )
            except Exception:
                logger.error(
                    "ingestion retry queue publication failed",
                    extra={
                        "operation": "ingestion",
                        "stage": "retry_publication",
                        "outcome": "error",
                        "error_code": "queue_unavailable",
                        "job_id": str(job.job_id),
                    },
                )

        logger.warning(
            "processing job %s stalled for %s (attempt %d/%d, next retry in %s)",
            job.job_id,
            backoff,
            attempt_count + 1,
            self._config.max_attempts,
            backoff,
            extra={
                "job_id": str(job.job_id),
                "attempt_count": attempt_count + 1,
                "max_attempts": self._config.max_attempts,
                "next_retry_in": str(backoff),
                "error_category": "transient",
            },
        )
        return True

    async def record_permanent_failure(
        self,
        job: ProcessingJob,
        error_code: str,
        reason: str,
    ) -> None:
        """Record a permanent failure that should not be retried."""
        await self._jobs.fail(
            job.job_id,
            error_code,
            datetime.now(UTC),
            error_category="permanent",
            failure_reason=reason,
        )
        INGESTION_JOB_EVENTS.labels(outcome="failed").inc()
        INGESTION_TERMINAL_FAILURES.labels(error_code=error_code).inc()
        logger.error(
            "processing job %s marked failed: %s (reason: %s)",
            job.job_id,
            error_code,
            reason,
            extra={
                "job_id": str(job.job_id),
                "error_code": error_code,
                "failure_reason": reason,
                "error_category": "permanent",
            },
        )
