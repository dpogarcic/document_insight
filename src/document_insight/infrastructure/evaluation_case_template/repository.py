"""SQLAlchemy reader for seeded evaluation case templates."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_case_template.model import (
    EvaluationCaseTemplateModel,
)
from document_insight.infrastructure.evaluation_case_template.protocol import (
    EvaluationCaseTemplate,
    EvaluationCaseTemplateRepository,
)


class SqlAlchemyEvaluationCaseTemplateRepository(EvaluationCaseTemplateRepository):
    """Read the migration-owned template catalog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> tuple[EvaluationCaseTemplate, ...]:
        """Return all scenarios in their stable suggested order."""
        models = await self._session.scalars(
            select(EvaluationCaseTemplateModel).order_by(EvaluationCaseTemplateModel.sort_order)
        )
        return tuple(
            EvaluationCaseTemplate(
                model.id,
                model.key,
                model.title,
                model.question,
                model.answerability,
                model.review_rubric,
                model.scenario_tag,
            )
            for model in models
        )
