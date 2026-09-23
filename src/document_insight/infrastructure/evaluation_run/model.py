"""ORM model for one durable evaluation run."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class EvaluationRunModel(Base):
    """An immutable comparison request with mutable execution state."""

    __tablename__ = "evaluation_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    suite_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_suite_revisions.id"), nullable=False, index=True
    )
    corpus_manifest: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    baseline_profile_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    candidate_profile_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    config_fingerprints: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    read_cohorts: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False, default=dict)
    candidate_component_profiles: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    evaluator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    k_values: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    requester_id: Mapped[UUID] = mapped_column(nullable=False)
    evaluation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="query")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)
    comparison_valid: Mapped[bool] = mapped_column(default=True, nullable=False)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
