"""SQLAlchemy model for citation-ready, lexically indexed text chunks."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class ChunkModel(Base):
    """One immutable text passage indexed under a document version."""

    __tablename__ = "chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "index_generation_id",
            "ordinal",
            name="uq_chunks_index_generation_ordinal",
        ),
        Index("ix_chunks_tenant_document_version", "tenant_id", "document_version_id"),
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    index_generation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("index_generations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        Text().with_variant(TSVECTOR, "postgresql"),
        server_default=FetchedValue(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
