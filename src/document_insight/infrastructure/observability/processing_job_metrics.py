"""Prometheus adapter for durable processing-job monitoring."""

from prometheus_client import Counter, Gauge, Histogram

from document_insight.application.jobs.models import JobStatus, ProcessingJobMetricsSnapshot

PROCESSING_JOBS = Gauge(
    "document_insight_processing_jobs",
    "Current durable processing-job records by authoritative status.",
    ("status",),
    multiprocess_mode="mostrecent",
)
PROCESSING_OLDEST_QUEUED_AGE_SECONDS = Gauge(
    "document_insight_processing_oldest_queued_age_seconds",
    "Age of the oldest durable queued processing job, or zero when none exist.",
    multiprocess_mode="mostrecent",
)
PROCESSING_OLDEST_IN_FLIGHT_AGE_SECONDS = Gauge(
    "document_insight_processing_oldest_in_flight_age_seconds",
    "Age of the oldest durable processing job in progress, or zero when none exist.",
    multiprocess_mode="mostrecent",
)
PROCESSING_RETRY_SCHEDULED = Gauge(
    "document_insight_processing_retry_scheduled_jobs",
    "Durable processing jobs currently awaiting a scheduled retry.",
    multiprocess_mode="mostrecent",
)
INGESTION_STAGE_DURATION = Histogram(
    "document_insight_ingestion_stage_duration_seconds",
    "Ingestion stage duration by bounded stage and outcome.",
    ("stage", "outcome"),
)
INGESTION_JOB_EVENTS = Counter(
    "document_insight_ingestion_job_events_total",
    "Durable ingestion lifecycle events by bounded outcome.",
    ("outcome",),
)
INGESTION_TERMINAL_FAILURES = Counter(
    "document_insight_ingestion_terminal_failures_total",
    "Terminal ingestion failures by safe error code.",
    ("error_code",),
)
INGESTION_RECONCILIATION_EVENTS = Counter(
    "document_insight_ingestion_reconciliation_events_total",
    "Reconciler outcomes by bounded outcome.",
    ("outcome",),
)
INGESTION_WORKER_LAST_SUCCESS = Gauge(
    "document_insight_ingestion_worker_last_success_unixtime",
    "Unix timestamp of the last successful ingestion job completion.",
    multiprocess_mode="max",
)
INGESTION_WORKER_LAST_HEARTBEAT = Gauge(
    "document_insight_ingestion_worker_last_heartbeat_unixtime",
    "Unix timestamp of the last RQ worker heartbeat.",
    multiprocess_mode="max",
)
INGESTION_RECONCILER_LAST_SUCCESS = Gauge(
    "document_insight_ingestion_reconciler_last_success_unixtime",
    "Unix timestamp of the last successful reconciliation pass.",
    multiprocess_mode="max",
)


class PrometheusProcessingJobMetrics:
    """Publish only aggregate, durable job monitoring signals."""

    def record_snapshot(self, snapshot: ProcessingJobMetricsSnapshot) -> None:
        """Set gauges from one authoritative database snapshot."""
        counts = dict(snapshot.counts_by_status)
        for status in JobStatus:
            PROCESSING_JOBS.labels(status=status.value).set(counts.get(status, 0))
        PROCESSING_OLDEST_QUEUED_AGE_SECONDS.set(snapshot.oldest_queued_age_seconds)
        PROCESSING_OLDEST_IN_FLIGHT_AGE_SECONDS.set(snapshot.oldest_processing_age_seconds)
        PROCESSING_RETRY_SCHEDULED.set(snapshot.retry_scheduled_count)
