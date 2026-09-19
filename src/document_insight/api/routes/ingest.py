"""Document ingestion endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from document_insight.api.dependencies import (
    ApplicationSettings,
    get_current_user,
    get_ingestion_service,
)
from document_insight.api.schemas.ingest import IngestStoredResponse
from document_insight.application.ingestion.contracts import IngestDocumentCommand
from document_insight.application.ingestion.service import IngestionService
from document_insight.domain.auth import AuthenticatedUser

router = APIRouter(tags=["documents"])
IngestionServiceDependency = Annotated[IngestionService, Depends(get_ingestion_service)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.post(
    "/ingest",
    response_model=IngestStoredResponse,
    status_code=status.HTTP_203_NON_AUTHORITATIVE_INFORMATION,
)
async def ingest_document(
    file: Annotated[UploadFile, File(description="PDF or image document, maximum 25 MiB")],
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
) -> IngestStoredResponse:
    """Validate and store an original; queue acceptance is implemented separately."""
    content = await file.read(settings.upload_max_bytes + 1)
    command = IngestDocumentCommand(
        content=content,
        filename=file.filename or "document",
        declared_content_type=file.content_type,
        document_id=document_id,
        department_ids=tuple(department_ids or ()),
        actor=current_user,
    )
    stored = await service.ingest(command)

    return IngestStoredResponse(
        document_id=stored.document_id,
        document_version_id=stored.document_version_id,
        version_number=stored.version_number,
    )
