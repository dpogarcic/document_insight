"""Tests for worker liveness metrics independent of job completion."""

from unittest.mock import Mock

import pytest
from rq import Worker

from document_insight.worker import monitored


def test_idle_worker_refreshes_heartbeat_before_staleness_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short dequeue timeout lets idle workers report progress frequently."""
    worker = object.__new__(monitored.MonitoredWorker)
    redis_heartbeats = Mock()
    metric = Mock()
    monkeypatch.setattr(Worker, "heartbeat", redis_heartbeats)
    monkeypatch.setattr(monitored.INGESTION_WORKER_LAST_HEARTBEAT, "set", metric)
    monkeypatch.setattr(monitored, "time", lambda: 1234.0)

    assert worker.dequeue_timeout == 15
    worker.heartbeat()

    redis_heartbeats.assert_called_once_with(None, None)
    metric.assert_called_once_with(1234.0)


def test_failed_redis_heartbeat_does_not_report_worker_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis heartbeat failure cannot advance the health timestamp."""
    worker = object.__new__(monitored.MonitoredWorker)
    metric = Mock()
    monkeypatch.setattr(Worker, "heartbeat", Mock(side_effect=OSError("redis unavailable")))
    monkeypatch.setattr(monitored.INGESTION_WORKER_LAST_HEARTBEAT, "set", metric)

    with pytest.raises(OSError):
        worker.heartbeat()

    metric.assert_not_called()
