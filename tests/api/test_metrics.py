"""Tests for the private Prometheus metrics endpoint."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from document_insight.api.metrics import metrics_response
from document_insight.application.jobs.models import JobStatus, ProcessingJobMetricsSnapshot
from document_insight.config import Settings
from document_insight.infrastructure.observability.processing_job_metrics import (
    PrometheusProcessingJobMetrics,
)
from document_insight.infrastructure.observability.provider_metrics import ProviderCallMetrics
from document_insight.infrastructure.observability.query_metrics import PrometheusQueryMetrics


def request_with_authorization(authorization: str | None) -> Request:
    """Build a minimal HTTP request without invoking application infrastructure."""
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    return Request({"type": "http", "method": "GET", "path": "/metrics", "headers": headers})


def test_metrics_requires_the_configured_bearer_token() -> None:
    """Metrics do not disclose operational data to callers without the monitoring secret."""
    settings = Settings(jwt_secret_key="test-secret", metrics_bearer_token="metrics-secret")

    response = metrics_response(request_with_authorization("Bearer metrics-secret"), settings)

    assert response.status_code == 200
    assert b"document_insight_http_requests_total" in response.body
    assert b"document_insight_rag_stage_duration_seconds" in response.body


def test_rag_metrics_use_only_bounded_operational_labels() -> None:
    """RAG telemetry accepts fixed stages and outcomes, never request-derived identifiers."""
    metrics = PrometheusQueryMetrics()

    metrics.observe_stage_duration("generation", "success", 0.1)
    metrics.observe_candidate_count("reranking", 3)
    metrics.increment_insufficient_evidence("below_evidence_threshold")

    response = metrics_response(
        request_with_authorization("Bearer metrics-secret"),
        Settings(jwt_secret_key="test-secret", metrics_bearer_token="metrics-secret"),
    )
    assert b'stage="generation"' in response.body
    assert b'outcome="success"' in response.body
    assert b'reason="below_evidence_threshold"' in response.body


def test_provider_metrics_distinguish_retryable_and_rate_limit_failures() -> None:
    """Provider telemetry exposes bounded dependency failure categories."""
    ProviderCallMetrics("mistral", "embedding").retryable_failure("provider_unavailable")
    ProviderCallMetrics("mistral", "generation").rate_limited()

    response = metrics_response(
        request_with_authorization("Bearer metrics-secret"),
        Settings(jwt_secret_key="test-secret", metrics_bearer_token="metrics-secret"),
    )

    assert b"document_insight_provider_retryable_failures_total" in response.body
    assert b"document_insight_provider_rate_limit_failures_total" in response.body


def test_processing_job_metrics_publish_aggregate_durable_state() -> None:
    """Processing metrics expose statuses and ages, never job or tenant identifiers."""
    PrometheusProcessingJobMetrics().record_snapshot(
        ProcessingJobMetricsSnapshot(
            counts_by_status=((JobStatus.QUEUED, 2), (JobStatus.FAILED, 1)),
            oldest_queued_age_seconds=12.0,
            oldest_processing_age_seconds=4.0,
            retry_scheduled_count=1,
        )
    )

    response = metrics_response(
        request_with_authorization("Bearer metrics-secret"),
        Settings(jwt_secret_key="test-secret", metrics_bearer_token="metrics-secret"),
    )

    assert b'document_insight_processing_jobs{status="queued"} 2.0' in response.body
    assert b'document_insight_processing_jobs{status="failed"} 1.0' in response.body
    assert b"document_insight_processing_oldest_queued_age_seconds 12.0" in response.body


def test_metrics_hide_data_for_an_invalid_bearer_token() -> None:
    """A token mismatch is indistinguishable from an unavailable metrics endpoint."""
    settings = Settings(jwt_secret_key="test-secret", metrics_bearer_token="metrics-secret")

    with pytest.raises(HTTPException) as error:
        metrics_response(request_with_authorization("Bearer incorrect"), settings)

    assert error.value.status_code == 404


def test_metrics_are_hidden_when_monitoring_is_not_configured() -> None:
    """Production cannot accidentally expose a scrape endpoint without a secret."""
    settings = Settings(jwt_secret_key="test-secret")

    with pytest.raises(HTTPException) as error:
        metrics_response(request_with_authorization(None), settings)

    assert error.value.status_code == 404
