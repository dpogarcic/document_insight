"""SQLAlchemy repository for labelled test cases."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_test_case.model import EvaluationTestCaseModel
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
    EvaluationTestCaseRepository,
)


class SqlAlchemyEvaluationTestCaseRepository(EvaluationTestCaseRepository):
    """Own immutable case labels without mutating suite revisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, revision_id: UUID, cases: tuple[EvaluationTestCase, ...]) -> None:
        self._session.add_all(
            [
                EvaluationTestCaseModel(
                    id=case.case_id,
                    suite_revision_id=revision_id,
                    question=case.question,
                    filter_text=case.filter_text,
                    authorized_identity_id=case.authorized_identity_id,
                    answerability=case.answerability.value,
                    expected_facts=case.expected_facts,
                    review_rubric=case.review_rubric,
                    tags=case.tags,
                    relevant_passage_ids=list(case.relevant_passage_ids),
                    relevance_complete=case.relevance_complete,
                    sort_order=case.sort_order,
                )
                for case in cases
            ]
        )

    async def list_for_revision(self, revision_id: UUID) -> tuple[EvaluationTestCase, ...]:
        models = await self._session.scalars(
            select(EvaluationTestCaseModel)
            .where(EvaluationTestCaseModel.suite_revision_id == revision_id)
            .order_by(EvaluationTestCaseModel.sort_order)
        )
        return tuple(
            EvaluationTestCase(
                model.id,
                model.suite_revision_id,
                model.question,
                model.filter_text,
                model.authorized_identity_id,
                Answerability(model.answerability),
                model.expected_facts,
                model.review_rubric,
                model.tags,
                tuple(model.relevant_passage_ids),
                model.sort_order,
                model.relevance_complete,
            )
            for model in models
        )
