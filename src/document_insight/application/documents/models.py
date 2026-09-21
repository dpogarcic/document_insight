"""Document-library result models."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from document_insight.application.ingestion.models import DocumentVersionStatus


@dataclass(frozen=True, slots=True)
class LibraryDepartment:
    """A department available to the current user for filtering or ingestion."""

    department_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class LibraryVersion:
    """Latest immutable version visible in a library row."""

    document_version_id: UUID
    version_number: int
    original_filename: str
    status: DocumentVersionStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryDocument:
    """A document row assembled after authorization and metadata loading."""

    document_id: UUID
    title: str
    departments: tuple[LibraryDepartment, ...]
    current_ready_version_id: UUID | None
    latest_version: LibraryVersion | None
    versions: tuple[LibraryVersion, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentLibrary:
    """Authorized document rows and the caller's available department filters."""

    documents: tuple[LibraryDocument, ...]
    departments: tuple[LibraryDepartment, ...]
