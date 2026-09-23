"""ORM model for one case and variant result."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class EvaluationCaseResultModel(Base):
    """Immutable query trace with separately reviewed answer quality."""

    __tablename__ = "evaluation_case_results"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[UUID] = mapped_column(nullable=False)
    variant: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    lexical_ranked_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lexical_cohort_ranked_ids: Mapped[dict[str, list[str]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    vector_cohort_ranked_ids: Mapped[dict[str, list[str]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    vector_combined_ranked_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    fused_ranked_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reranked_ranked_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    final_citations: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    answer_text: Mapped[str | None] = mapped_column(nullable=True)
    answerability_outcome: Mapped[str | None] = mapped_column(nullable=True)
    provider_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    stage_latencies_ms: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    measurements: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    answer_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    answer_quality_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
