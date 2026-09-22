"""Port definitions for privacy-safe live RAG telemetry."""

from typing import Protocol


class QueryMetrics(Protocol):
    """Record bounded operational signals without query or retrieval content."""

    def observe_stage_duration(self, stage: str, outcome: str, duration_seconds: float) -> None:
        """Record one bounded RAG-stage duration."""

    def observe_query_duration(self, outcome: str, duration_seconds: float) -> None:
        """Record one end-to-end RAG-query duration."""

    def observe_candidate_count(self, stage: str, count: int) -> None:
        """Record the shape of one retrieval stage without candidate identities."""

    def increment_insufficient_evidence(self, reason: str) -> None:
        """Record a safe, bounded insufficient-evidence outcome."""

    def observe_citation_count(self, count: int) -> None:
        """Record the number of citations returned by a grounded response."""

    def observe_evidence_confidence(self, confidence: float) -> None:
        """Record calibrated evidence confidence, never model self-confidence."""


class NullQueryMetrics:
    """No-op telemetry used when the application service is composed outside the API."""

    def observe_stage_duration(self, stage: str, outcome: str, duration_seconds: float) -> None:
        """Discard the stage observation."""

    def observe_query_duration(self, outcome: str, duration_seconds: float) -> None:
        """Discard the query observation."""

    def observe_candidate_count(self, stage: str, count: int) -> None:
        """Discard the candidate-count observation."""

    def increment_insufficient_evidence(self, reason: str) -> None:
        """Discard the insufficient-evidence observation."""

    def observe_citation_count(self, count: int) -> None:
        """Discard the citation-count observation."""

    def observe_evidence_confidence(self, confidence: float) -> None:
        """Discard the evidence-confidence observation."""
