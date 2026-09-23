"""HTTP behavior for the authenticated per-user query quota."""

from collections import defaultdict
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from document_insight.api.app import create_app
from document_insight.api.dependencies import (
    get_current_user,
    get_query_preparation_service,
    get_query_rate_limiter,
)
from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.query.models import QueryResult
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.security.query_rate_limiter import (
    RateLimitDecision,
    RateLimitUnavailableError,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run HTTP tests on the application's asyncio runtime."""
    return "asyncio"


class _RecordingLimiter:
    """Reserve a bounded quota independently for each authenticated user."""

    def __init__(self) -> None:
        self.counts: dict[tuple[UUID, UUID], int] = defaultdict(int)
        self.unavailable = False

    async def acquire(
        self, tenant_id: UUID, user_id: UUID, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        if self.unavailable:
            raise RateLimitUnavailableError
        key = (tenant_id, user_id)
        self.counts[key] += 1
        return RateLimitDecision(self.counts[key] <= limit, window_seconds)


class _RecordingQueryService:
    """Record whether a request reached retrieval preparation."""

    def __init__(self) -> None:
        self.calls = 0

    async def query(self, command: object) -> QueryResult:
        self.calls += 1
        return QueryResult("Authorized response.", 0.0, (), ())


@pytest.mark.anyio
async def test_query_quota_is_per_user_and_rejects_before_service() -> None:
    """The third query is rejected while another user keeps an independent quota."""
    tenant_id, department_id, first_user, second_user = (uuid4() for _ in range(4))
    actor = AuthorizationContext(first_user, tenant_id, (department_id,), UserRole.VIEWER)
    limiter = _RecordingLimiter()
    service = _RecordingQueryService()
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret_key=SecretStr("test-secret-key-that-is-long-enough"),
        query_rate_limit_requests=2,
        query_rate_limit_window_seconds=60,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_query_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_query_preparation_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        responses = [
            await client.post("/query", json={"question": "What is in the document?"})
            for _ in range(3)
        ]
        actor = AuthorizationContext(second_user, tenant_id, (department_id,), UserRole.VIEWER)
        other_user = await client.post("/query", json={"question": "What is in the document?"})

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[2].json()["detail"]["code"] == "query_rate_limit_exceeded"
    assert responses[2].headers["retry-after"] == "60"
    assert other_user.status_code == 200
    assert service.calls == 3
    assert limiter.counts[(tenant_id, first_user)] == 3
    assert limiter.counts[(tenant_id, second_user)] == 1


@pytest.mark.anyio
async def test_query_fails_closed_when_quota_store_is_unavailable() -> None:
    """A Redis outage cannot silently disable the public query quota."""
    actor = AuthorizationContext(uuid4(), uuid4(), (uuid4(),), UserRole.VIEWER)
    limiter = _RecordingLimiter()
    limiter.unavailable = True
    service = _RecordingQueryService()
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret_key=SecretStr("test-secret-key-that-is-long-enough"),
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_query_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_query_preparation_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/query", json={"question": "What is in the document?"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "query_rate_limit_unavailable"
    assert service.calls == 0
