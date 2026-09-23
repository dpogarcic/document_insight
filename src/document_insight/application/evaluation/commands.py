"""Commands for initiating evaluation runs."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LaunchEvaluationRunCommand:
    """Command to launch an evaluation run.

    Supports both query profile evaluations (against existing indexes) and
    ingestion profile evaluations (with isolated evaluation index generations).
    """

    suite_revision_id: UUID
    # Baseline (current active) profile IDs for comparison
    baseline_profile_ids: tuple[UUID, ...]
    # Candidate profile IDs being evaluated
    candidate_profile_ids: tuple[UUID, ...]
    # Read cohorts: lexical and embedding profile IDs used
    read_cohorts: dict[str, tuple[UUID, ...]]
    # Component profiles for the candidate bundle (for ingestion evals)
    candidate_component_profiles: dict[str, UUID] | None
    # Corpus/index manifest describing the evaluation corpus snapshot
    corpus_manifest: dict[str, object]
    # Evaluator version for reproducibility
    evaluator_version: str
    # K values for precision/recall calculations
    k_values: tuple[int, ...]
    # Requester identity
    requester_id: UUID
    # Evaluation mode: "query" or "ingestion"
    evaluation_mode: str


@dataclass(frozen=True, slots=True)
class EvaluationRunRecord:
    """Persisted run information for tracking and display."""

    run_id: UUID
    suite_revision_id: UUID
    suite_name: str
    revision_number: int
    status: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    baseline_profile_ids: tuple[UUID, ...]
    candidate_profile_ids: tuple[UUID, ...]
    config_fingerprints: dict[str, str]
    k_values: tuple[int, ...]
    case_count: int
    completed_case_count: int
    evaluation_mode: str
    comparison_valid: bool
    tenant_id: UUID | None = None
