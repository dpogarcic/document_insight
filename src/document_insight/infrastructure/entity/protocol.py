"""Repository contract for canonical version-scoped entity metadata."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.processing.models import CanonicalEntity, DocumentLanguage


@dataclass(frozen=True, slots=True)
class CreateEntities:
    """Deduplicated NER metadata to persist for one document version."""

    document_version_id: UUID
    tenant_id: UUID
    language: DocumentLanguage
    ner_provider: str
    ner_model: str
    entities: tuple[CanonicalEntity, ...]


class EntityRepository(Protocol):
    """Persist canonical entity metadata owned by one document version."""

    async def create_many(self, command: CreateEntities) -> None:
        """Create one deduplicated row per label/value pair."""
