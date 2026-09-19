"""Domain values for storing immutable document originals."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class StoredMediaType(StrEnum):
    """File formats accepted by the first ingestion slice."""

    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"


@dataclass(frozen=True, slots=True)
class StoredDocumentVersion:
    """Identifiers and provenance for an original persisted before queueing."""

    document_id: UUID
    document_version_id: UUID
    version_number: int
    object_key: str
    media_type: StoredMediaType
    size_bytes: int
    content_sha256: str
