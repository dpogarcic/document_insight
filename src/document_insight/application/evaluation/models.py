"""Application models for evaluation runs."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TestCaseResult:
    """Result from evaluating a single test case.

    Uses version-stable source anchors (strings) for passage identification.
    """

    case_id: UUID
    status: str
    # Version-stable source anchors after lexical retrieval
    lexical_ranked_ids: tuple[str, ...]
    # Per-cohort vector results (cohort_id -> ranked anchors)
    vector_cohort_ranked_ids: dict[str, tuple[str, ...]]
    # Combined vector results across all cohorts
    vector_combined_ranked_ids: tuple[str, ...]
    # Fused (RRF) ranked anchors
    fused_ranked_ids: tuple[str, ...]
    # Reranked ranked anchors
    reranked_ranked_ids: tuple[str, ...]
    # Final citations with source anchors
    final_citations: tuple[dict[str, object], ...]
    # Generated answer text
    answer_text: str | None
    # Answerability outcome
    answerability_outcome: str | None
    # Provider errors
    provider_errors: tuple[str, ...]
    # Stage latencies in milliseconds
    stage_latencies_ms: dict[str, float]
    lexical_cohort_ranked_ids: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True, slots=True)
class EvaluationCaseInput:
    """Input for evaluating a single test case."""

    case_id: UUID
    question: str
    filter_text: str | None
    authorized_identity_id: UUID
    answerability: str
    expected_facts: dict[str, object] | None
    review_rubric: str | None
    relevant_passage_ids: tuple[str, ...]  # Version-stable source anchors
    tags: dict[str, str]


@dataclass(frozen=True, slots=True)
class CorpusVariant:
    """Exact indexed versions and mapping to the suite's original source versions."""

    version_ids: tuple[UUID, ...]
    source_versions: dict[UUID, UUID]

    def to_json(self) -> dict[str, object]:
        """Encode only immutable IDs for PostgreSQL JSON storage."""
        return {
            "version_ids": [str(value) for value in self.version_ids],
            "source_versions": {
                str(indexed): str(source) for indexed, source in self.source_versions.items()
            },
        }

    @classmethod
    def from_json(cls, raw: object) -> "CorpusVariant":
        """Reject malformed or unmapped persisted evaluation corpora."""
        if not isinstance(raw, dict):
            raise ValueError("Evaluation corpus variant is missing")
        versions = raw.get("version_ids")
        mapping = raw.get("source_versions")
        if not isinstance(versions, list) or not isinstance(mapping, dict):
            raise ValueError("Evaluation corpus variant is incomplete")
        version_ids = tuple(UUID(str(value)) for value in versions)
        source_versions = {
            UUID(str(indexed)): UUID(str(source)) for indexed, source in mapping.items()
        }
        if not version_ids or any(value not in source_versions for value in version_ids):
            raise ValueError("Every indexed version needs a source mapping")
        return cls(version_ids, source_versions)


@dataclass(frozen=True, slots=True)
class EvaluationCorpusManifest:
    """Paired baseline and candidate corpora for one immutable suite revision."""

    suite_fingerprint: str
    baseline: CorpusVariant
    candidate: CorpusVariant
    baseline_query_profile_id: UUID
    candidate_query_profile_id: UUID
    baseline_ingestion_profile_id: UUID | None = None
    candidate_ingestion_profile_id: UUID | None = None

    def to_json(self) -> dict[str, object]:
        """Serialize the complete run input without secrets or document text."""
        return {
            "suite_fingerprint": self.suite_fingerprint,
            "baseline": self.baseline.to_json(),
            "candidate": self.candidate.to_json(),
            "baseline_query_profile_id": str(self.baseline_query_profile_id),
            "candidate_query_profile_id": str(self.candidate_query_profile_id),
            "baseline_ingestion_profile_id": (
                str(self.baseline_ingestion_profile_id)
                if self.baseline_ingestion_profile_id
                else None
            ),
            "candidate_ingestion_profile_id": (
                str(self.candidate_ingestion_profile_id)
                if self.candidate_ingestion_profile_id
                else None
            ),
        }

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> "EvaluationCorpusManifest":
        """Revalidate persisted run inputs before running any provider calls."""
        fingerprint = raw.get("suite_fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("Evaluation suite fingerprint is invalid")
        return cls(
            fingerprint,
            CorpusVariant.from_json(raw.get("baseline")),
            CorpusVariant.from_json(raw.get("candidate")),
            UUID(str(raw.get("baseline_query_profile_id"))),
            UUID(str(raw.get("candidate_query_profile_id"))),
            UUID(str(raw["baseline_ingestion_profile_id"]))
            if raw.get("baseline_ingestion_profile_id")
            else None,
            UUID(str(raw["candidate_ingestion_profile_id"]))
            if raw.get("candidate_ingestion_profile_id")
            else None,
        )
