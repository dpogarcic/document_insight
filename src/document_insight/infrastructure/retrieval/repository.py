"""PostgreSQL retrieval adapter with mandatory authorization predicates."""

from uuid import UUID

from sqlalchemy import Float, exists, func, literal, or_, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement, Select

from document_insight.infrastructure.chunk.model import ChunkModel
from document_insight.infrastructure.chunk_embedding.model import ChunkEmbeddingModel
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.entity.model import EntityModel
from document_insight.infrastructure.index_generation.model import IndexGenerationModel
from document_insight.infrastructure.ingestion_profile.model import IngestionProfileModel
from document_insight.infrastructure.retrieval.protocol import (
    AuthorizedRetrievalRepository,
    EntityMatch,
    RetrievalScope,
    RetrievedChunk,
)


class SqlAlchemyAuthorizedRetrievalRepository(AuthorizedRetrievalRepository):
    """Search only current document versions visible to the trusted scope.

    The department `EXISTS` predicate is included in every statement before ranking. This
    avoids retrieving a broader candidate pool and filtering it after relevance scoring.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_entity_matches(
        self, scope: RetrievalScope, filter_text: str, limit: int
    ) -> tuple[EntityMatch, ...]:
        """Find matching metadata on current document versions already in scope."""
        terms = tuple(term for term in filter_text.casefold().split() if term)
        if not terms or not scope.department_ids:
            return ()
        rows = await self._session.execute(
            select(EntityModel.document_version_id, EntityModel.display_value, EntityModel.label)
            .join(
                DocumentModel,
                DocumentModel.current_ready_version_id == EntityModel.document_version_id,
            )
            .where(
                EntityModel.tenant_id == scope.tenant_id,
                DocumentModel.tenant_id == scope.tenant_id,
                self._authorized_document_predicate(scope, DocumentModel.id),
                or_(*(EntityModel.normalized_value.contains(term) for term in terms)),
            )
            .order_by(EntityModel.occurrence_count.desc())
            .limit(limit)
        )
        return tuple(
            EntityMatch(version_id, display_value, label)
            for version_id, display_value, label in rows
        )

    async def lexical_search(
        self,
        scope: RetrievalScope,
        lexical_profile_id: UUID,
        query_text: str,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        """Use PostgreSQL full-text ranking as the temporary authorized lexical branch."""
        if not scope.department_ids:
            return ()
        tsquery = func.websearch_to_tsquery("simple", query_text)
        rank = func.ts_rank_cd(ChunkModel.search_vector, tsquery).label("rank")
        rows = await self._session.execute(
            self._chunk_statement(scope)
            .join(IndexGenerationModel, IndexGenerationModel.id == ChunkModel.index_generation_id)
            .join(
                IngestionProfileModel,
                IngestionProfileModel.id == IndexGenerationModel.ingestion_profile_id,
            )
            .where(
                IngestionProfileModel.lexical_profile_id == lexical_profile_id,
                IndexGenerationModel.status == "ready",
                ChunkModel.search_vector.op("@@")(tsquery),
            )
            .add_columns(rank)
            .order_by(rank.desc(), ChunkModel.id)
            .limit(limit)
        )
        return self._chunks_from_rows(rows)

    async def vector_search(
        self,
        scope: RetrievalScope,
        embedding_profile_id: UUID,
        vector: tuple[float, ...],
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        """Search only one compatible vector cohort and map distance to bounded similarity."""
        if not scope.department_ids:
            return ()
        distance = ChunkEmbeddingModel.embedding.op("<=>")(vector)
        # Keep the scalar similarity constant numeric. Without an explicit type,
        # SQLAlchemy coerces it to the vector column's custom type and attempts to
        # serialize ``1.0`` as a vector before issuing the query.
        similarity = (literal(1.0, type_=Float()) - distance).label("rank")
        rows = await self._session.execute(
            self._chunk_statement(scope)
            .join(ChunkEmbeddingModel, ChunkEmbeddingModel.chunk_id == ChunkModel.id)
            .join(IndexGenerationModel, IndexGenerationModel.id == ChunkModel.index_generation_id)
            .where(
                ChunkEmbeddingModel.embedding_profile_id == embedding_profile_id,
                IndexGenerationModel.status == "ready",
            )
            .add_columns(similarity)
            .order_by(distance, ChunkModel.id)
            .limit(limit)
        )
        return self._chunks_from_rows(rows)

    @staticmethod
    def _chunks_from_rows(
        rows: Result[tuple[UUID, UUID, UUID, str, str, int, float]],
    ) -> tuple[RetrievedChunk, ...]:
        """Convert selected columns to framework-independent typed candidates."""
        return tuple(
            RetrievedChunk(
                chunk_id, document_id, version_id, title, text, page_number, float(score)
            )
            for chunk_id, document_id, version_id, title, text, page_number, score in rows
        )

    @staticmethod
    def _authorized_document_predicate(
        scope: RetrievalScope, document_id: ColumnElement[UUID] | InstrumentedAttribute[UUID]
    ) -> ColumnElement[bool]:
        """Build a correlated department predicate used before every retrieval rank."""
        return exists(
            select(DocumentDepartmentModel.document_id).where(
                DocumentDepartmentModel.document_id == document_id,
                DocumentDepartmentModel.tenant_id == scope.tenant_id,
                DocumentDepartmentModel.department_id.in_(scope.department_ids),
            )
        )

    def _chunk_statement(
        self, scope: RetrievalScope
    ) -> Select[tuple[UUID, UUID, UUID, str, str, int]]:
        """Select active chunks after tenant and department policy predicates."""
        return (
            select(
                ChunkModel.id,
                DocumentModel.id,
                ChunkModel.document_version_id,
                DocumentModel.title,
                ChunkModel.text,
                ChunkModel.page_number,
            )
            .join(
                DocumentModel,
                DocumentModel.current_ready_version_id == ChunkModel.document_version_id,
            )
            .where(
                ChunkModel.tenant_id == scope.tenant_id,
                DocumentModel.tenant_id == scope.tenant_id,
                self._authorized_document_predicate(scope, DocumentModel.id),
            )
        )
