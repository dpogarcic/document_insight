"""Repository contract for one evaluation case and variant result."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class CaseResultStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    """Captured ranks, citations, answer, and manual score for one case variant."""

    result_id: UUID
    run_id: UUID
    case_id: UUID
    status: CaseResultStatus
    lexical_ranked_ids: tuple[str, ...]
    vector_cohort_ranked_ids: dict[str, tuple[str, ...]]
    vector_combined_ranked_ids: tuple[str, ...]
    fused_ranked_ids: tuple[str, ...]
    reranked_ranked_ids: tuple[str, ...]
    final_citations: tuple[dict[str, object], ...]
    answer_text: str | None
    answerability_outcome: str | None
    provider_errors: tuple[str, ...]
    stage_latencies_ms: dict[str, float]
    started_at: str
    completed_at: str | None
    variant: str = "candidate"
    measurements: tuple[dict[str, object], ...] = ()
    answer_quality_score: float | None = None
    answer_quality_note: str | None = None
    lexical_cohort_ranked_ids: dict[str, tuple[str, ...]] | None = None


class EvaluationCaseResultRepository(Protocol):
    """Own persisted outcomes without mutating run or suite rows."""

    async def add(self, result: EvaluationCaseResult) -> None: ...
    async def list_for_run(self, run_id: UUID) -> tuple[EvaluationCaseResult, ...]: ...
    async def set_answer_quality(self, result_id: UUID, score: float, note: str) -> None: ...
