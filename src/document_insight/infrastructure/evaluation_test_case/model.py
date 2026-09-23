"""ORM model for one immutable labelled test case."""

from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class EvaluationTestCaseModel(Base):
    """One question, identity, and set of source-span labels."""

    __tablename__ = "evaluation_test_cases"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    suite_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_suite_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(nullable=False)
    filter_text: Mapped[str | None] = mapped_column(nullable=True)
    authorized_identity_id: Mapped[UUID] = mapped_column(nullable=False)
    answerability: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_facts: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    review_rubric: Mapped[str | None] = mapped_column(nullable=True)
    tags: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    relevant_passage_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    relevance_complete: Mapped[bool] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
