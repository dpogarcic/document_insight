"""Tests for the private Prometheus metrics endpoint."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from document_insight.api.metrics import metrics_response
from document_insight.config import Settings


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
