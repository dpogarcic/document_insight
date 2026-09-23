"""ORM model for one immutable evaluation suite revision."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class EvaluationSuiteRevisionModel(Base):
    """A named suite revision bound to one tenant's selected corpus."""

    __tablename__ = "evaluation_suite_revisions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    suite_name: Mapped[str] = mapped_column(String(200), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    evaluation_tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    corpus_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
