"""Repository contract for durable evaluation run state."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from document_insight.infrastructure.evaluation_aggregate.protocol import AggregateMeasurement
from document_insight.infrastructure.evaluation_case_result.protocol import (
    EvaluationCaseResult,
)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """One persisted comparison request and its execution state."""

    run_id: UUID
    suite_revision_id: UUID
    corpus_manifest: dict[str, object]
    baseline_profile_ids: tuple[UUID, ...]
    candidate_profile_ids: tuple[UUID, ...]
    config_fingerprints: dict[str, str]
    read_cohorts: dict[str, tuple[UUID, ...]]
    candidate_component_profiles: dict[str, UUID] | None
    evaluator_version: str
    k_values: tuple[int, ...]
    requester_id: UUID
    evaluation_mode: str
    status: RunStatus
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    per_case_results: tuple[EvaluationCaseResult, ...]
    aggregate_measurements: tuple[AggregateMeasurement, ...]
    comparison_valid: bool
    enqueued_at: str | None = None
    heartbeat_at: str | None = None


class EvaluationRunRepository(Protocol):
    """Own only evaluation run rows; services coordinate child records."""

    async def create_run(self, run: EvaluationRun) -> UUID: ...
    async def get_run(self, run_id: UUID) -> EvaluationRun | None: ...
    async def claim_pending(self, run_id: UUID, started_at: str) -> bool: ...
    async def list_pending_ids(self) -> tuple[UUID, ...]: ...
    async def mark_enqueued(self, run_id: UUID, enqueued_at: str) -> None: ...
    async def touch_heartbeat(self, run_id: UUID, at: str) -> None: ...
    async def fail_stale_running(self, stale_before: str, at: str) -> tuple[UUID, ...]: ...
    async def list_runs(
        self, suite_revision_id: UUID | None = None, status: RunStatus | None = None
    ) -> tuple[EvaluationRun, ...]: ...
    async def update_run_status(
        self,
        run_id: UUID,
        status: RunStatus,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_message: str | None = None,
    ) -> None: ...
