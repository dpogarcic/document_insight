"""Unit tests for Redis Queue delivery and its inert worker entry point."""

import logging
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from document_insight.application.ingestion.exceptions import QueueUnavailableError
from document_insight.infrastructure.queue.rq import RqProcessingQueue
from document_insight.worker import ingestion


@pytest.mark.anyio
async def test_rq_queue_publishes_only_job_and_correlation_ids() -> None:
    """RQ receives a stable job ID, while content remains outside the queue message."""
    processing_queue = RqProcessingQueue("redis://localhost:6379/0", "ingestion")
    enqueue = Mock()
    processing_queue._queue.enqueue = enqueue
    job_id = uuid4()
    correlation_id = uuid4()

    await processing_queue.enqueue_ingestion(job_id, correlation_id)

    enqueue.assert_called_once_with(
        "document_insight.worker.ingestion.process_ingestion_job",
        str(job_id),
        str(correlation_id),
        job_id=str(job_id),
        description=f"Process ingestion job {job_id}",
        result_ttl=0,
    )


@pytest.mark.anyio
async def test_rq_queue_translates_connection_failures() -> None:
    """Redis failures do not expose provider exceptions to application code."""
    processing_queue = RqProcessingQueue("redis://localhost:6379/0", "ingestion")
    processing_queue._queue.enqueue = Mock(side_effect=ConnectionError("unavailable"))

    with pytest.raises(QueueUnavailableError):
        await processing_queue.enqueue_ingestion(uuid4(), uuid4())


@pytest.mark.anyio
async def test_rq_queue_schedules_retry_at_the_durable_retry_time() -> None:
    """Delayed retries use RQ's scheduler API rather than passing timing as job data."""
    processing_queue = RqProcessingQueue("redis://localhost:6379/0", "ingestion")
    enqueue_at = Mock()
    processing_queue._queue.enqueue_at = enqueue_at
    job_id = uuid4()
    correlation_id = uuid4()
    retry_at = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)

    await processing_queue.re_enqueue_for_retry(job_id, correlation_id, retry_at)

    enqueue_at.assert_called_once_with(
        retry_at,
        "document_insight.worker.ingestion.process_ingestion_job",
        str(job_id),
        str(correlation_id),
        job_id=str(job_id),
        description=f"Retry ingestion job {job_id} at {retry_at}",
        result_ttl=0,
    )


def test_worker_entry_point_runs_the_parsing_workflow(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker delegates processing under the queued correlation identifier."""
    job_id = uuid4()
    correlation_id = uuid4()
    processed: list[object] = []

    async def fake_process(value: object) -> None:
        processed.append(value)

    monkeypatch.setattr(ingestion, "_process", fake_process)

    with caplog.at_level(logging.INFO):
        ingestion.process_ingestion_job(str(job_id), str(correlation_id))

    assert processed == [job_id]
    assert "processing checkpoint completed" in caplog.text
