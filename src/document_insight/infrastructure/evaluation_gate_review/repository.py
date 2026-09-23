"""SQLAlchemy repository for operator gate decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_gate_review.model import GateReviewModel
from document_insight.infrastructure.evaluation_gate_review.protocol import (
    EvaluationGateReviewRepository,
    GateReview,
)


class SqlAlchemyEvaluationGateReviewRepository(EvaluationGateReviewRepository):
    """Own append-only gate review rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, review: GateReview) -> UUID:
        self._session.add(
            GateReviewModel(
                id=review.review_id,
                run_id=review.run_id,
                operator_id=review.operator_id,
                decision=review.decision,
                reason=review.reason,
                reviewed_run_id=review.reviewed_run_id,
                threshold_revision=review.threshold_revision,
                created_at=datetime.fromisoformat(review.created_at),
            )
        )
        return review.review_id

    async def get_for_run(self, run_id: UUID) -> GateReview | None:
        model = await self._session.scalar(
            select(GateReviewModel).where(GateReviewModel.run_id == run_id)
        )
        return None if model is None else self._to_record(model)

    async def list_reviews(self, operator_id: UUID | None = None) -> tuple[GateReview, ...]:
        stmt = select(GateReviewModel).order_by(GateReviewModel.created_at.desc())
        if operator_id is not None:
            stmt = stmt.where(GateReviewModel.operator_id == operator_id)
        models = await self._session.scalars(stmt)
        return tuple(self._to_record(model) for model in models)

    @staticmethod
    def _to_record(model: GateReviewModel) -> GateReview:
        return GateReview(
            model.id,
            model.run_id,
            model.operator_id,
            model.decision,
            model.reason,
            model.reviewed_run_id,
            model.created_at.isoformat(),
            model.threshold_revision,
        )
