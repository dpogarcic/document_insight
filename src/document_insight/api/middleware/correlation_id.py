"""Request correlation identifiers for tracing API work across boundaries."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_ID_HEADER = b"x-correlation-id"
correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)
logger = logging.getLogger(__name__)


class CorrelationIdMiddleware:
    """Assign one safe correlation ID to each HTTP request and response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        correlation_id = self._resolve_correlation_id(scope)
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started_at = perf_counter()
        response_status: int | None = None

        async def send_with_correlation_id(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                headers = [
                    header
                    for header in message.get("headers", [])
                    if header[0].lower() != CORRELATION_ID_HEADER
                ]
                headers.append((CORRELATION_ID_HEADER, correlation_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        with correlation_id_scope(correlation_id):
            await self._app(scope, receive, send_with_correlation_id)
            logger.info(
                "HTTP request completed",
                extra={
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                    "request_method": scope["method"],
                    "request_path": scope["path"],
                    "response_status": response_status,
                },
            )

    @staticmethod
    def _resolve_correlation_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() == CORRELATION_ID_HEADER:
                try:
                    return str(UUID(value.decode("ascii")))
                except (UnicodeDecodeError, ValueError):
                    break
        return str(uuid4())


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current asynchronous request context."""
    return correlation_id_context.get()


@contextmanager
def correlation_id_scope(correlation_id: str) -> Iterator[None]:
    """Temporarily bind a correlation ID to the current asynchronous context."""
    context_token = correlation_id_context.set(correlation_id)
    try:
        yield
    finally:
        correlation_id_context.reset(context_token)
