"""SQLAlchemy models for immutable query configuration bundles and cohorts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base, utc_now


class QueryProfileModel(Base):
    """One immutable reranking, generation, and retrieval-settings bundle."""

    __tablename__ = "query_profiles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    reranker_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capability_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    retrieval_snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("configuration_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class QueryProfileLexicalCohortModel(Base):
    """One lexical profile a query bundle is allowed to read."""

    __tablename__ = "query_profile_lexical_cohorts"
    __table_args__ = (
        ForeignKeyConstraint(["query_profile_id"], ["query_profiles.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["lexical_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
    )

    query_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    lexical_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)


class QueryProfileEmbeddingCohortModel(Base):
    """One embedding profile a query bundle is allowed to read."""

    __tablename__ = "query_profile_embedding_cohorts"
    __table_args__ = (
        ForeignKeyConstraint(["query_profile_id"], ["query_profiles.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["embedding_profile_id"], ["capability_profiles.id"], ondelete="RESTRICT"
        ),
    )

    query_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    embedding_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
