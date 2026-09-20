"""Commands accepted by the document-ingestion application service."""

from dataclasses import dataclass
from uuid import UUID

from document_insight.application.auth.models import AuthorizationContext


@dataclass(frozen=True, slots=True)
class IngestDocumentCommand:
    """Validated transport data and authenticated scope for one upload."""

    content: bytes
    filename: str
    declared_content_type: str | None
    document_id: UUID | None
    department_ids: tuple[UUID, ...]
    actor: AuthorizationContext
    correlation_id: UUID
