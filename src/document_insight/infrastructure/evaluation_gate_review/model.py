"""ORM model for one operator evaluation gate decision."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class GateReviewModel(Base):
    """Append-only operator decision on an exact completed run."""

    __tablename__ = "evaluation_gate_reviews"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    operator_id: Mapped[UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    reviewed_run_id: Mapped[UUID] = mapped_column(nullable=False)
    threshold_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
