"""Bounded Prometheus telemetry for external AI provider calls."""

from time import perf_counter

from prometheus_client import Counter, Histogram

PROVIDER_REQUESTS = Counter(
    "document_insight_provider_requests_total",
    "External AI provider requests by provider, capability, and outcome.",
    ("provider", "capability", "outcome"),
)
PROVIDER_DURATION_SECONDS = Histogram(
    "document_insight_provider_request_duration_seconds",
    "External AI provider request duration by provider, capability, and outcome.",
    ("provider", "capability", "outcome"),
)
PROVIDER_FAILURES = Counter(
    "document_insight_provider_failures_total",
    "External AI provider failures by bounded safe error category.",
    ("provider", "capability", "error_code"),
)
PROVIDER_RETRYABLE_FAILURES = Counter(
    "document_insight_provider_retryable_failures_total",
    "Retryable external AI provider failures.",
    ("provider", "capability", "error_code"),
)
PROVIDER_RATE_LIMIT_FAILURES = Counter(
    "document_insight_provider_rate_limit_failures_total",
    "External AI provider requests rejected by a rate limit.",
    ("provider", "capability"),
)


class ProviderCallMetrics:
    """Record a single provider call without model, prompt, or customer data labels."""

    def __init__(self, provider: str, capability: str) -> None:
        self._labels = {"provider": provider, "capability": capability}
        self._started_at = perf_counter()

    def success(self) -> None:
        """Record a successful provider call."""
        self._observe("success")

    def failure(self, error_code: str) -> None:
        """Record a bounded provider failure category."""
        PROVIDER_FAILURES.labels(**self._labels, error_code=error_code).inc()
        self._observe("error")

    def retryable_failure(self, error_code: str) -> None:
        """Record a retryable failure using a safe, bounded error category."""
        PROVIDER_FAILURES.labels(**self._labels, error_code=error_code).inc()
        PROVIDER_RETRYABLE_FAILURES.labels(**self._labels, error_code=error_code).inc()
        self._observe("error")

    def rate_limited(self) -> None:
        """Record a rate-limited provider call."""
        PROVIDER_FAILURES.labels(**self._labels, error_code="rate_limited").inc()
        PROVIDER_RATE_LIMIT_FAILURES.labels(**self._labels).inc()
        self._observe("rate_limited")

    def _observe(self, outcome: str) -> None:
        PROVIDER_REQUESTS.labels(**self._labels, outcome=outcome).inc()
        PROVIDER_DURATION_SECONDS.labels(**self._labels, outcome=outcome).observe(
            perf_counter() - self._started_at
        )
