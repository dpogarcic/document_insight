"""Persisted, corpus-independent evaluation case templates."""

from uuid import UUID

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class EvaluationCaseTemplateModel(Base):
    """A seeded scenario that an operator can adapt into an immutable case."""

    __tablename__ = "evaluation_case_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    question: Mapped[str] = mapped_column(nullable=False)
    answerability: Mapped[str] = mapped_column(String(20), nullable=False)
    review_rubric: Mapped[str] = mapped_column(nullable=False)
    scenario_tag: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
