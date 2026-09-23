"""SQLAlchemy repository for case and variant outcomes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_case_result.model import EvaluationCaseResultModel
from document_insight.infrastructure.evaluation_case_result.protocol import (
    CaseResultStatus,
    EvaluationCaseResult,
    EvaluationCaseResultRepository,
)


class SqlAlchemyEvaluationCaseResultRepository(EvaluationCaseResultRepository):
    """Own case result rows and later manual quality fields."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, result: EvaluationCaseResult) -> None:
        self._session.add(
            EvaluationCaseResultModel(
                id=result.result_id,
                run_id=result.run_id,
                case_id=result.case_id,
                status=result.status.value,
                variant=result.variant,
                lexical_ranked_ids=list(result.lexical_ranked_ids),
                lexical_cohort_ranked_ids={
                    key: list(values)
                    for key, values in (result.lexical_cohort_ranked_ids or {}).items()
                },
                vector_cohort_ranked_ids={
                    key: list(values) for key, values in result.vector_cohort_ranked_ids.items()
                },
                vector_combined_ranked_ids=list(result.vector_combined_ranked_ids),
                fused_ranked_ids=list(result.fused_ranked_ids),
                reranked_ranked_ids=list(result.reranked_ranked_ids),
                final_citations=list(result.final_citations),
                answer_text=result.answer_text,
                answerability_outcome=result.answerability_outcome,
                provider_errors=list(result.provider_errors),
                stage_latencies_ms=result.stage_latencies_ms,
                measurements=list(result.measurements),
                answer_quality_score=result.answer_quality_score,
                answer_quality_note=result.answer_quality_note,
                started_at=datetime.fromisoformat(result.started_at),
                completed_at=(
                    datetime.fromisoformat(result.completed_at) if result.completed_at else None
                ),
            )
        )

    async def list_for_run(self, run_id: UUID) -> tuple[EvaluationCaseResult, ...]:
        models = await self._session.scalars(
            select(EvaluationCaseResultModel)
            .where(EvaluationCaseResultModel.run_id == run_id)
            .order_by(EvaluationCaseResultModel.started_at)
        )
        return tuple(self._to_record(model) for model in models)

    async def set_answer_quality(self, result_id: UUID, score: float, note: str) -> None:
        await self._session.execute(
            update(EvaluationCaseResultModel)
            .where(
                EvaluationCaseResultModel.id == result_id,
                EvaluationCaseResultModel.answer_quality_score.is_(None),
            )
            .values(answer_quality_score=score, answer_quality_note=note)
        )

    @staticmethod
    def _to_record(model: EvaluationCaseResultModel) -> EvaluationCaseResult:
        return EvaluationCaseResult(
            result_id=model.id,
            run_id=model.run_id,
            case_id=model.case_id,
            status=CaseResultStatus(model.status),
            lexical_ranked_ids=tuple(model.lexical_ranked_ids),
            lexical_cohort_ranked_ids={
                key: tuple(values) for key, values in model.lexical_cohort_ranked_ids.items()
            },
            vector_cohort_ranked_ids={
                key: tuple(values) for key, values in model.vector_cohort_ranked_ids.items()
            },
            vector_combined_ranked_ids=tuple(model.vector_combined_ranked_ids),
            fused_ranked_ids=tuple(model.fused_ranked_ids),
            reranked_ranked_ids=tuple(model.reranked_ranked_ids),
            final_citations=tuple(model.final_citations),
            answer_text=model.answer_text,
            answerability_outcome=model.answerability_outcome,
            provider_errors=tuple(model.provider_errors),
            stage_latencies_ms=model.stage_latencies_ms,
            measurements=tuple(model.measurements),
            answer_quality_score=model.answer_quality_score,
            answer_quality_note=model.answer_quality_note,
            started_at=model.started_at.isoformat(),
            completed_at=model.completed_at.isoformat() if model.completed_at else None,
            variant=model.variant,
        )
