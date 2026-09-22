"""Shared bounded retry policy for Mistral rate-limit responses."""

MAX_RATE_LIMIT_ATTEMPTS = 4
INITIAL_RATE_LIMIT_DELAY_SECONDS = 5.0


def retry_delay_seconds(attempt: int) -> float:
    """Return a bounded exponential delay for a zero-based retry attempt."""
    return INITIAL_RATE_LIMIT_DELAY_SECONDS * (2**attempt)
