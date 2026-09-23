"""SQLAlchemy repository for aggregate evaluation measurements."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_aggregate.model import AggregateMeasurementModel
from document_insight.infrastructure.evaluation_aggregate.protocol import (
    AggregateMeasurement,
    EvaluationAggregateRepository,
)


class SqlAlchemyEvaluationAggregateRepository(EvaluationAggregateRepository):
    """Own aggregate metric rows only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, measurement: AggregateMeasurement) -> None:
        self._session.add(
            AggregateMeasurementModel(
                id=measurement.measurement_id,
                run_id=measurement.run_id,
                metric_name=measurement.metric_name,
                metric_value=measurement.metric_value,
                case_count=measurement.case_count,
                numerator=measurement.numerator,
                denominator=measurement.denominator,
                definition=measurement.definition,
                variant=measurement.variant,
                stage=measurement.stage,
                k=measurement.k,
                cohort_id=measurement.cohort_id,
            )
        )

    async def list_for_run(self, run_id: UUID) -> tuple[AggregateMeasurement, ...]:
        models = await self._session.scalars(
            select(AggregateMeasurementModel)
            .where(AggregateMeasurementModel.run_id == run_id)
            .order_by(AggregateMeasurementModel.metric_name)
        )
        return tuple(
            AggregateMeasurement(
                model.id,
                model.run_id,
                model.metric_name,
                model.metric_value,
                model.case_count,
                model.numerator,
                model.denominator,
                model.definition,
                model.variant,
                model.stage,
                model.k,
                model.cohort_id,
            )
            for model in models
        )
