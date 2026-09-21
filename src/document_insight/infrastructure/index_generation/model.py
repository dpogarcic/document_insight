"""SQLAlchemy model for one document-version index generation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class IndexGenerationModel(Base):
    """Derived chunks and vectors built with one immutable ingestion profile."""

    __tablename__ = "index_generations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_version_id", "ingestion_profile_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    ingestion_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    chunking_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lexical_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
