"""Document-department association ORM model."""

from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from document_insight.infrastructure.database.base import Base


class DocumentDepartmentModel(Base):
    """Source-of-truth many-to-many document department assignment."""

    __tablename__ = "document_departments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["department_id", "tenant_id"],
            ["departments.id", "departments.tenant_id"],
            ondelete="RESTRICT",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    department_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
