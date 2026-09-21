"""Document query preparation endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from document_insight.api.dependencies import get_current_user, get_query_preparation_service
from document_insight.api.schemas.query import QueryPreparedDTO, QueryRequest
from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.service import QueryPreparationService

router = APIRouter(tags=["query"])


@router.post(
    "/query",
    response_model=QueryPreparedDTO,
)
async def query_documents(
    request: QueryRequest,
    current_user: Annotated[AuthorizationContext, Depends(get_current_user)],
    service: Annotated[QueryPreparationService, Depends(get_query_preparation_service)],
) -> QueryPreparedDTO:
    """Authenticate and prepare a bounded retrieval request without retrieving data yet."""
    prepared = await service.prepare(
        PrepareQueryCommand(
            question=request.question,
            filter_text=request.filter,
            top_k=request.top_k,
            actor=current_user,
        )
    )
    return QueryPreparedDTO(
        query_profile_id=prepared.query_profile_id,
        lexical_profile_ids=list(prepared.lexical_profile_ids),
        embedding_profile_ids=list(prepared.embedding_profile_ids),
        authorized_department_ids=list(prepared.department_ids),
        filter=prepared.filter_text,
        top_k=prepared.top_k,
    )
