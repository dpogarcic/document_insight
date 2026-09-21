"""SQLAlchemy model for an immutable ingestion capability bundle."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class IngestionProfileModel(Base):
    """Bundle NER, chunking, lexical, and embedding profile versions."""

    __tablename__ = "ingestion_profiles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    ner_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chunking_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lexical_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    embedding_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
