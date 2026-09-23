"""Atomic per-user query throttling backed by shared Redis state."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Whether a query may run and when a rejected caller may retry."""

    allowed: bool
    retry_after_seconds: int


class QueryRateLimiter(Protocol):
    """Reserve one query for an authenticated user before retrieval starts."""

    async def acquire(
        self, tenant_id: UUID, user_id: UUID, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        """Return the atomic per-user quota decision for one query request."""


class RateLimitUnavailableError(Exception):
    """Shared rate-limit state could not be checked safely."""


_ACQUIRE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('TTL', KEYS[1])
if ttl == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    ttl = tonumber(ARGV[2])
end
if ttl < 1 then ttl = 1 end
return {count <= tonumber(ARGV[1]) and 1 or 0, ttl}
"""


class RedisQueryRateLimiter(QueryRateLimiter):
    """Use one Redis script so concurrent API processes share a single quota."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def acquire(
        self, tenant_id: UUID, user_id: UUID, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        """Increment the user's fixed-duration window and return its decision."""
        key = f"document-insight:query-rate:{tenant_id}:{user_id}"
        try:
            # redis-py's async execute_command has no return annotation.
            result = await self._client.execute_command(  # type: ignore[no-untyped-call]
                "EVAL", _ACQUIRE_SCRIPT, 1, key, str(limit), str(window_seconds)
            )
        except RedisError as error:
            raise RateLimitUnavailableError from error
        if not isinstance(result, list) or len(result) != 2:
            raise RateLimitUnavailableError
        try:
            allowed = int(result[0]) == 1
            retry_after = max(1, int(result[1]))
        except (TypeError, ValueError) as error:
            raise RateLimitUnavailableError from error
        return RateLimitDecision(allowed, retry_after)
