"""SQLAlchemy model for canonical document-version entity metadata."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class EntityModel(Base):
    """One deduplicated entity fact scoped to an immutable document version."""

    __tablename__ = "entities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_version_id", "label", "normalized_value"),
        Index("ix_entities_tenant_label_normalized", "tenant_id", "label", "normalized_value"),
        CheckConstraint("occurrence_count > 0", name="occurrence_count_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    display_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    ner_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    ner_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
