"""Document-ingestion models used by the application layer."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class DocumentMediaType(StrEnum):
    """File formats accepted by the first ingestion slice."""

    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"


class DocumentLanguage(StrEnum):
    """Languages supported by the initial local NER provider."""

    ENGLISH = "en"
    CROATIAN = "hr"


class DocumentVersionStatus(StrEnum):
    """Lifecycle states for an immutable document version."""

    STORED = "stored"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Durable identifiers and provenance returned after storing an upload."""

    document_id: UUID
    document_version_id: UUID
    job_id: UUID
    version_number: int
    object_key: str
    media_type: DocumentMediaType
    size_bytes: int
    content_sha256: str
