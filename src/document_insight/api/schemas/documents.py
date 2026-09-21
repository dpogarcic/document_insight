"""Response schemas for the authorized document library."""

from datetime import datetime
from uuid import UUID

from document_insight.api.schemas.common import ApiModel
from document_insight.application.ingestion.models import DocumentVersionStatus


class DepartmentDTO(ApiModel):
    """Tenant-scoped department metadata safe to display to the caller."""

    department_id: UUID
    name: str


class DocumentVersionDTO(ApiModel):
    """Most recent immutable version shown for a logical document."""

    document_version_id: UUID
    version_number: int
    original_filename: str
    status: DocumentVersionStatus
    created_at: datetime


class DocumentDTO(ApiModel):
    """Authorized document-library row."""

    document_id: UUID
    title: str
    departments: list[DepartmentDTO]
    current_ready_version_id: UUID | None
    latest_version: DocumentVersionDTO | None
    versions: list[DocumentVersionDTO]
    created_at: datetime


class DocumentLibraryDTO(ApiModel):
    """Documents and department filters available to the authenticated caller."""

    documents: list[DocumentDTO]
    departments: list[DepartmentDTO]


class ActivateDocumentVersionRequest(ApiModel):
    """Tenant-admin selection of one ready immutable document version."""

    document_version_id: UUID


class ActivatedDocumentVersionDTO(ApiModel):
    """The logical document pointer after a successful explicit activation."""

    document_id: UUID
    current_ready_version_id: UUID
