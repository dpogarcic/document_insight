"""ORM model for one aggregate evaluation measurement."""

from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class AggregateMeasurementModel(Base):
    """Auditable aggregate numerator, denominator, and definition."""

    __tablename__ = "evaluation_aggregates"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    variant: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    k: Mapped[int | None] = mapped_column(nullable=True)
    cohort_id: Mapped[UUID | None] = mapped_column(nullable=True)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    numerator: Mapped[int | None] = mapped_column(Integer, nullable=True)
    denominator: Mapped[int | None] = mapped_column(Integer, nullable=True)
    definition: Mapped[str] = mapped_column(String(500), nullable=False)
