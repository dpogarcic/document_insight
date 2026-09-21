"""SQLAlchemy model for an embedding generated under one exact profile."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now
from document_insight.infrastructure.database.vector import PgVector


class ChunkEmbeddingModel(Base):
    """Reserved vector row with immutable embedding-profile provenance.

    Its dimension is declared by the immutable embedding profile, allowing one table to
    hold transition cohorts without treating incompatible vectors as comparable.
    """

    __tablename__ = "chunk_embeddings"
    __table_args__ = (UniqueConstraint("chunk_id", "embedding_profile_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(PgVector(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
