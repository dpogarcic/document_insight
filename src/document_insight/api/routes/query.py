"""Document query preparation endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from document_insight.api.dependencies import get_current_user, get_query_preparation_service
from document_insight.api.schemas.query import (
    DetectedEntityDTO,
    QueryDTO,
    QueryRequest,
    SourceCitationDTO,
)
from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.service import QueryPreparationService

router = APIRouter(tags=["query"])


@router.post(
    "/query",
    response_model=QueryDTO,
)
async def query_documents(
    request: QueryRequest,
    current_user: Annotated[AuthorizationContext, Depends(get_current_user)],
    service: Annotated[QueryPreparationService, Depends(get_query_preparation_service)],
) -> QueryDTO:
    """Execute one authorization-bounded hybrid RAG query."""
    result = await service.query(
        PrepareQueryCommand(
            question=request.question,
            filter_text=request.filter,
            top_k=request.top_k,
            actor=current_user,
        )
    )
    return QueryDTO(
        answer=result.answer,
        confidence=result.confidence,
        sources=[
            SourceCitationDTO(
                document_id=citation.document_id,
                document_version_id=citation.document_version_id,
                chunk_id=citation.chunk_id,
                page_number=citation.page_number,
                quote=citation.quote,
                relevance_score=citation.relevance_score,
            )
            for citation in result.citations
        ],
        entities=[
            DetectedEntityDTO(
                document_version_id=entity.document_version_id,
                text=entity.text,
                label=entity.label,
            )
            for entity in result.entities
        ],
    )
