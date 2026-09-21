"""SQLAlchemy model for the mutable active-profile pointers."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class ActiveProfileModel(Base):
    """One atomically switched profile pointer for a runtime scope and kind."""

    __tablename__ = "active_profiles"
    __table_args__ = (
        UniqueConstraint("scope", "profile_kind"),
        CheckConstraint(
            "(profile_kind = 'ingestion' AND ingestion_profile_id IS NOT NULL AND query_profile_id IS NULL) "
            "OR (profile_kind = 'query' AND query_profile_id IS NOT NULL AND ingestion_profile_id IS NULL)",
            name="matching_profile_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ingestion_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_profiles.id", ondelete="RESTRICT")
    )
    query_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("query_profiles.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
