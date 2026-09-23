"""Verify atomic per-user query quotas against disposable Redis."""

import asyncio
from uuid import uuid4

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import ConnectionPool, Redis

from document_insight.infrastructure.security.query_rate_limiter import RedisQueryRateLimiter


class _TestRedisSettings(BaseSettings):
    """Load only the optional disposable Redis test endpoint."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_redis_url: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    """Run async Redis checks on asyncio."""
    return "asyncio"


@pytest.mark.anyio
async def test_concurrent_queries_share_one_per_user_quota() -> None:
    """Concurrent API processes cannot each consume the same remaining slot."""
    url = _TestRedisSettings().test_redis_url
    if not url:
        pytest.skip("TEST_REDIS_URL is required for Redis integration checks")
    client = Redis(connection_pool=ConnectionPool.from_url(url))
    limiter = RedisQueryRateLimiter(client)
    tenant_id, first_user, second_user, other_tenant = (uuid4() for _ in range(4))
    keys = tuple(
        f"document-insight:query-rate:{tenant}:{user}"
        for tenant, user in (
            (tenant_id, first_user),
            (tenant_id, second_user),
            (other_tenant, first_user),
        )
    )
    try:
        decisions = await asyncio.gather(
            *(limiter.acquire(tenant_id, first_user, 3, 60) for _ in range(10))
        )
        assert sum(decision.allowed for decision in decisions) == 3
        assert all(1 <= decision.retry_after_seconds <= 60 for decision in decisions)
        assert (await limiter.acquire(tenant_id, second_user, 3, 60)).allowed
        assert (await limiter.acquire(other_tenant, first_user, 3, 60)).allowed
    finally:
        await client.delete(*keys)
        await client.aclose()
