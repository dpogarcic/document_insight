"""Prometheus implementation of the live RAG telemetry port."""

from prometheus_client import Counter, Histogram

from document_insight.application.query.metrics import QueryMetrics

RAG_STAGE_DURATION_SECONDS = Histogram(
    "document_insight_rag_stage_duration_seconds",
    "RAG stage duration by bounded stage and outcome.",
    ("stage", "outcome"),
)
RAG_QUERY_DURATION_SECONDS = Histogram(
    "document_insight_rag_query_duration_seconds",
    "End-to-end RAG query duration by outcome.",
    ("outcome",),
)
RAG_CANDIDATE_COUNT = Histogram(
    "document_insight_rag_candidate_count",
    "Candidate count after a bounded RAG retrieval stage.",
    ("stage",),
)
RAG_INSUFFICIENT_EVIDENCE = Counter(
    "document_insight_rag_insufficient_evidence_total",
    "RAG queries stopped because grounded evidence was insufficient.",
    ("reason",),
)
RAG_CITATION_COUNT = Histogram(
    "document_insight_rag_citation_count",
    "Citations returned by grounded RAG responses.",
)
RAG_EVIDENCE_CONFIDENCE = Histogram(
    "document_insight_rag_evidence_confidence",
    "Calibrated evidence-confidence distribution for grounded RAG responses.",
)


class PrometheusQueryMetrics(QueryMetrics):
    """Expose only bounded, content-free live RAG measurements."""

    def observe_stage_duration(self, stage: str, outcome: str, duration_seconds: float) -> None:
        """Record a stage duration."""
        RAG_STAGE_DURATION_SECONDS.labels(stage=stage, outcome=outcome).observe(duration_seconds)

    def observe_query_duration(self, outcome: str, duration_seconds: float) -> None:
        """Record a full query duration."""
        RAG_QUERY_DURATION_SECONDS.labels(outcome=outcome).observe(duration_seconds)

    def observe_candidate_count(self, stage: str, count: int) -> None:
        """Record a non-negative candidate count."""
        RAG_CANDIDATE_COUNT.labels(stage=stage).observe(count)

    def increment_insufficient_evidence(self, reason: str) -> None:
        """Record an insufficient-evidence outcome."""
        RAG_INSUFFICIENT_EVIDENCE.labels(reason=reason).inc()

    def observe_citation_count(self, count: int) -> None:
        """Record a citation count."""
        RAG_CITATION_COUNT.observe(count)

    def observe_evidence_confidence(self, confidence: float) -> None:
        """Record an already-calibrated evidence-confidence score."""
        RAG_EVIDENCE_CONFIDENCE.observe(confidence)
