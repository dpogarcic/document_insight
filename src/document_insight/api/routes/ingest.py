"""Document ingestion endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from document_insight.api.dependencies import (
    ApplicationSettings,
    get_current_user,
    get_ingestion_service,
)
from document_insight.api.schemas.ingest import IngestStoredDTO
from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.ingestion.commands import IngestDocumentCommand
from document_insight.application.ingestion.service import IngestionService

router = APIRouter(tags=["documents"])
IngestionServiceDependency = Annotated[IngestionService, Depends(get_ingestion_service)]
CurrentUser = Annotated[AuthorizationContext, Depends(get_current_user)]


@router.post(
    "/ingest",
    response_model=IngestStoredDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_document(
    file: Annotated[UploadFile, File(description="PDF or image document, maximum 25 MiB")],
    request: Request,
    current_user: CurrentUser,
    service: IngestionServiceDependency,
    settings: ApplicationSettings,
    document_id: Annotated[
        UUID | None,
        Form(description="Existing logical document to version; omit to create a new document"),
    ] = None,
    department_ids: Annotated[
        list[UUID] | None,
        Form(description="Initial departments selected by a tenant admin for a new document"),
    ] = None,
) -> IngestStoredDTO:
    """Validate, store, and enqueue an immutable document version for processing."""
    content = await file.read(settings.upload_max_bytes + 1)
    command = IngestDocumentCommand(
        content=content,
        filename=file.filename or "document",
        declared_content_type=file.content_type,
        document_id=document_id,
        department_ids=tuple(department_ids or ()),
        actor=current_user,
        correlation_id=UUID(request.state.correlation_id),
    )
    stored = await service.ingest(command)

    return IngestStoredDTO(
        document_id=stored.document_id,
        document_version_id=stored.document_version_id,
        job_id=stored.job_id,
        version_number=stored.version_number,
    )
