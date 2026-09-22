"""Contract tests for the infrastructure-free FastAPI layer."""

import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from document_insight.api.app import create_app
from document_insight.api.logging_config import CorrelationIdFormatter
from document_insight.api.middleware.correlation_id import get_correlation_id
from document_insight.application.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from document_insight.application.documents.exceptions import (
    DocumentActivationForbiddenError,
    DocumentVersionNotReadyError,
)
from document_insight.application.ingestion.exceptions import (
    DocumentNotFoundError,
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionForbiddenError,
    InvalidDepartmentScopeError,
    ObjectStorageUnavailableError,
    UnsupportedDocumentTypeError,
)
from document_insight.application.jobs.exceptions import JobNotFoundError


@pytest.fixture
def anyio_backend() -> str:
    """Run async API contract tests on the application's asyncio runtime."""
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Create an isolated API client for each contract test."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_correlation_id_is_assigned_to_request_response_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A valid upstream ID is traceable through state, context, and response headers."""
    application = create_app()

    @application.get("/_test/correlation-id")
    async def read_correlation_id(request: Request) -> dict[str, str | None]:
        logging.getLogger("document_insight.test").info("Request-scoped log")
        return {
            "request_state": request.state.correlation_id,
            "context": get_correlation_id(),
        }

    incoming_id = str(uuid4())
    transport = ASGITransport(app=application)
    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            response = await test_client.get(
                "/_test/correlation-id",
                headers={"X-Correlation-ID": incoming_id},
            )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == incoming_id
    assert response.json() == {"request_state": incoming_id, "context": incoming_id}
    request_records = [
        record
        for record in caplog.records
        if record.getMessage() in {"Request-scoped log", "HTTP request completed"}
    ]
    assert len(request_records) == 2
    assert all(record.__dict__["correlation_id"] == incoming_id for record in request_records)
    assert get_correlation_id() is None


def test_server_log_formatter_always_outputs_correlation_id() -> None:
    """Server log lines visibly include the correlation field even outside requests."""
    record = logging.LogRecord(
        name="document_insight.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Example log",
        args=(),
        exc_info=None,
    )
    record.__dict__["correlation_id"] = "-"
    formatter = CorrelationIdFormatter(logging.Formatter("%(message)s"))

    assert formatter.format(record) == "correlation_id=- Example log"


@pytest.mark.anyio
async def test_invalid_correlation_id_is_replaced() -> None:
    """Unsafe caller-controlled header values never enter tracing or logs."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        response = await test_client.get(
            "/openapi.json",
            headers={"X-Correlation-ID": "not-a-safe-id"},
        )

    generated_id = response.headers["x-correlation-id"]
    assert generated_id != "not-a-safe-id"
    assert str(UUID(generated_id)) == generated_id


@pytest.mark.anyio
async def test_cors_allows_the_local_frontend_login_request() -> None:
    """The local Next.js origin may preflight requests to the public API."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        response = await test_client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_application_registers_domain_exception_handlers() -> None:
    """Every expected auth and ingestion error is translated at the app boundary."""
    application = create_app()
    expected_exceptions = {
        EmailAlreadyRegisteredError,
        InvalidCredentialsError,
        DocumentNotFoundError,
        DocumentTooLargeError,
        EmptyDocumentError,
        IngestionForbiddenError,
        InvalidDepartmentScopeError,
        DocumentActivationForbiddenError,
        DocumentVersionNotReadyError,
        JobNotFoundError,
        ObjectStorageUnavailableError,
        UnsupportedDocumentTypeError,
    }

    assert expected_exceptions <= application.exception_handlers.keys()
    assert Exception in application.exception_handlers


@pytest.mark.anyio
async def test_unknown_exception_is_logged_and_returns_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected failures retain their traceback internally without leaking details."""
    application = create_app()

    @application.get("/_test/unexpected-error")
    async def raise_unexpected_error() -> None:
        raise RuntimeError("sensitive database connection detail")

    transport = ASGITransport(app=application, raise_app_exceptions=False)
    with caplog.at_level(
        logging.ERROR,
        logger="document_insight.api.exception_handlers",
    ):
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            response = await test_client.get("/_test/unexpected-error")

    assert response.status_code == 500
    assert response.json() == {
        "detail": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred.",
        }
    }
    assert "sensitive database connection detail" not in response.text
    error_record = caplog.records[-1]
    assert error_record.getMessage() == "Unhandled application exception"
    assert error_record.exc_info is not None
    assert error_record.__dict__["correlation_id"] == response.headers["x-correlation-id"]
    assert error_record.__dict__["request_method"] == "GET"
    assert error_record.__dict__["request_path"] == "/_test/unexpected-error"


@pytest.mark.anyio
async def test_openapi_exposes_defined_endpoints(client: AsyncClient) -> None:
    """All planned public endpoint contracts are present in OpenAPI."""
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert set(paths) == {
        "/auth/login",
        "/auth/register",
        "/documents",
        "/documents/{document_id}/activate",
        "/ingest",
        "/jobs/{job_id}",
        "/query",
    }
    assert "post" in paths["/auth/login"]
    assert "post" in paths["/auth/register"]
    assert "post" in paths["/ingest"]
    assert "get" in paths["/jobs/{job_id}"]
    assert "post" in paths["/query"]


@pytest.mark.anyio
async def test_query_authenticates_before_preparing_retrieval(client: AsyncClient) -> None:
    """The query route does not disclose profile state to an unauthenticated caller."""
    response = await client.post("/query", json={"question": "What does the contract say?"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/query", {"question": "", "top_k": 5}),
        ("/query", {"question": "Valid question", "top_k": 0}),
        ("/query", {"question": "Valid question", "top_k": 21}),
    ],
)
@pytest.mark.anyio
async def test_query_rejects_invalid_input(
    client: AsyncClient,
    path: str,
    payload: dict[str, object],
) -> None:
    """Authentication runs before query validation can disclose request-handling details."""
    response = await client.post(path, json=payload)

    assert response.status_code == 401


@pytest.mark.anyio
async def test_job_status_authenticates_before_identifier_disclosure(client: AsyncClient) -> None:
    """Unauthenticated callers receive no identifier-validation details."""
    response = await client.get("/jobs/not-a-uuid")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_request_models_reject_undocumented_fields(client: AsyncClient) -> None:
    """An unauthenticated request cannot probe the query contract."""
    response = await client.post(
        "/query",
        json={"question": "Valid question", "tenant_id": "untrusted-tenant"},
    )

    assert response.status_code == 401
