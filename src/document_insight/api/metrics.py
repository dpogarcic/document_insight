"""Authenticated, low-cardinality Prometheus metrics for the API process."""

import hmac
from time import perf_counter

from fastapi import HTTPException, Request, Response, status
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from document_insight.config import Settings

HTTP_REQUESTS = Counter(
    "document_insight_http_requests_total",
    "Completed HTTP requests by method and status.",
    ("method", "status"),
)
HTTP_DURATION_SECONDS = Histogram(
    "document_insight_http_request_duration_seconds",
    "HTTP request duration by method and status.",
    ("method", "status"),
)


class PrometheusMetricsMiddleware:
    """Measure HTTP traffic without labeling unbounded resource identifiers."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self._app(scope, receive, send)
            return
        started_at = perf_counter()
        response_status = status.HTTP_500_INTERNAL_SERVER_ERROR

        async def observe_response(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, observe_response)
        finally:
            labels = {"method": scope["method"], "status": str(response_status)}
            HTTP_REQUESTS.labels(**labels).inc()
            HTTP_DURATION_SECONDS.labels(**labels).observe(perf_counter() - started_at)


def metrics_response(request: Request, settings: Settings) -> Response:
    """Return metrics only to a caller holding the configured monitoring secret."""
    authorize_metrics_request(request, settings)
    if settings.prometheus_multiproc_dir is None:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]  # lacks stubs
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


def authorize_metrics_request(request: Request, settings: Settings) -> None:
    """Reject metric scrapes that do not carry the configured monitoring secret."""
    configured_token = settings.metrics_bearer_token
    if configured_token is None or not configured_token.get_secret_value():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    supplied_header = request.headers.get("authorization", "")
    expected_header = f"Bearer {configured_token.get_secret_value()}"
    if not hmac.compare_digest(supplied_header, expected_header):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
