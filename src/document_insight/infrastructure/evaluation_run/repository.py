"""SQLAlchemy repository for durable evaluation run rows."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_run.model import EvaluationRunModel
from document_insight.infrastructure.evaluation_run.protocol import (
    EvaluationRun,
    EvaluationRunRepository,
    RunStatus,
)


def _datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class SqlAlchemyEvaluationRunRepository(EvaluationRunRepository):
    """Own one run's status and immutable execution inputs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, run: EvaluationRun) -> UUID:
        self._session.add(
            EvaluationRunModel(
                id=run.run_id,
                suite_revision_id=run.suite_revision_id,
                corpus_manifest=run.corpus_manifest,
                baseline_profile_ids=[str(value) for value in run.baseline_profile_ids],
                candidate_profile_ids=[str(value) for value in run.candidate_profile_ids],
                config_fingerprints=run.config_fingerprints,
                read_cohorts={
                    key: [str(value) for value in values]
                    for key, values in run.read_cohorts.items()
                },
                candidate_component_profiles=(
                    {key: str(value) for key, value in run.candidate_component_profiles.items()}
                    if run.candidate_component_profiles is not None
                    else None
                ),
                evaluator_version=run.evaluator_version,
                k_values=list(run.k_values),
                requester_id=run.requester_id,
                evaluation_mode=run.evaluation_mode,
                status=run.status.value,
                started_at=_datetime(run.started_at),
                completed_at=_datetime(run.completed_at),
                error_message=run.error_message,
                comparison_valid=run.comparison_valid,
                enqueued_at=_datetime(run.enqueued_at),
                heartbeat_at=_datetime(run.heartbeat_at),
            )
        )
        return run.run_id

    async def get_run(self, run_id: UUID) -> EvaluationRun | None:
        model = await self._session.scalar(
            select(EvaluationRunModel).where(EvaluationRunModel.id == run_id)
        )
        return None if model is None else self._to_run(model)

    async def claim_pending(self, run_id: UUID, started_at: str) -> bool:
        result = await self._session.execute(
            update(EvaluationRunModel)
            .where(EvaluationRunModel.id == run_id, EvaluationRunModel.status == "pending")
            .values(
                status="running",
                started_at=_datetime(started_at),
                heartbeat_at=_datetime(started_at),
            )
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    async def list_pending_ids(self) -> tuple[UUID, ...]:
        return tuple(
            await self._session.scalars(
                select(EvaluationRunModel.id).where(EvaluationRunModel.status == "pending")
            )
        )

    async def mark_enqueued(self, run_id: UUID, enqueued_at: str) -> None:
        await self._session.execute(
            update(EvaluationRunModel)
            .where(EvaluationRunModel.id == run_id, EvaluationRunModel.status == "pending")
            .values(enqueued_at=_datetime(enqueued_at))
        )

    async def touch_heartbeat(self, run_id: UUID, at: str) -> None:
        await self._session.execute(
            update(EvaluationRunModel)
            .where(EvaluationRunModel.id == run_id, EvaluationRunModel.status == "running")
            .values(heartbeat_at=_datetime(at))
        )

    async def fail_stale_running(self, stale_before: str, at: str) -> tuple[UUID, ...]:
        rows = await self._session.scalars(
            update(EvaluationRunModel)
            .where(
                EvaluationRunModel.status == "running",
                EvaluationRunModel.heartbeat_at < _datetime(stale_before),
            )
            .values(
                status="failed",
                completed_at=_datetime(at),
                error_message="Evaluation worker stopped before completion",
            )
            .returning(EvaluationRunModel.id)
        )
        return tuple(rows)

    async def list_runs(
        self, suite_revision_id: UUID | None = None, status: RunStatus | None = None
    ) -> tuple[EvaluationRun, ...]:
        stmt = select(EvaluationRunModel)
        if suite_revision_id is not None:
            stmt = stmt.where(EvaluationRunModel.suite_revision_id == suite_revision_id)
        if status is not None:
            stmt = stmt.where(EvaluationRunModel.status == status.value)
        models = await self._session.scalars(stmt.order_by(EvaluationRunModel.started_at.desc()))
        return tuple(self._to_run(model) for model in models)

    async def update_run_status(
        self,
        run_id: UUID,
        status: RunStatus,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {"status": status.value}
        if started_at is not None:
            updates["started_at"] = _datetime(started_at)
        if completed_at is not None:
            updates["completed_at"] = _datetime(completed_at)
        if error_message is not None:
            updates["error_message"] = error_message
        stmt = update(EvaluationRunModel).where(EvaluationRunModel.id == run_id)
        if status in (RunStatus.COMPLETED, RunStatus.FAILED):
            stmt = stmt.where(EvaluationRunModel.status == "running")
        await self._session.execute(stmt.values(**updates))

    @staticmethod
    def _to_run(model: EvaluationRunModel) -> EvaluationRun:
        return EvaluationRun(
            run_id=model.id,
            suite_revision_id=model.suite_revision_id,
            corpus_manifest=model.corpus_manifest,
            baseline_profile_ids=tuple(UUID(value) for value in model.baseline_profile_ids),
            candidate_profile_ids=tuple(UUID(value) for value in model.candidate_profile_ids),
            config_fingerprints=model.config_fingerprints,
            read_cohorts={
                key: tuple(UUID(value) for value in values)
                for key, values in model.read_cohorts.items()
            },
            candidate_component_profiles=(
                {key: UUID(value) for key, value in model.candidate_component_profiles.items()}
                if model.candidate_component_profiles is not None
                else None
            ),
            evaluator_version=model.evaluator_version,
            k_values=tuple(model.k_values),
            requester_id=model.requester_id,
            evaluation_mode=model.evaluation_mode,
            status=RunStatus(model.status),
            started_at=_iso(model.started_at),
            completed_at=_iso(model.completed_at),
            error_message=model.error_message,
            comparison_valid=model.comparison_valid,
            enqueued_at=_iso(model.enqueued_at),
            heartbeat_at=_iso(model.heartbeat_at),
            per_case_results=(),
            aggregate_measurements=(),
        )
