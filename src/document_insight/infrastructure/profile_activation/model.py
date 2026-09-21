"""SQLAlchemy model for activation auditing."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class ProfileActivationModel(Base):
    """Immutable record of one successful active-profile pointer switch."""

    __tablename__ = "profile_activations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_profile_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    new_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    active_profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
