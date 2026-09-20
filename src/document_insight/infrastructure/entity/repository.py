"""SQLAlchemy repository for canonical named-entity metadata."""

from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.entity.model import EntityModel
from document_insight.infrastructure.entity.protocol import CreateEntities, EntityRepository


class SqlAlchemyEntityRepository(EntityRepository):
    """Own canonical entity persistence without mutating stage metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, command: CreateEntities) -> None:
        """Create one unique metadata row for each canonical entity."""
        self._session.add_all(
            EntityModel(
                tenant_id=command.tenant_id,
                document_version_id=command.document_version_id,
                display_value=entity.display_value,
                normalized_value=entity.normalized_value,
                label=entity.label,
                occurrence_count=entity.occurrence_count,
                language=command.language,
                ner_provider=command.ner_provider,
                ner_model=command.ner_model,
            )
            for entity in command.entities
        )
