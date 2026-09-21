"""Authorized document-library endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from document_insight.api.dependencies import get_current_user, get_document_library_service
from document_insight.api.errors import AUTH_ERROR_RESPONSES
from document_insight.api.schemas.documents import (
    ActivatedDocumentVersionDTO,
    ActivateDocumentVersionRequest,
    DepartmentDTO,
    DocumentDTO,
    DocumentLibraryDTO,
    DocumentVersionDTO,
)
from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.documents.service import DocumentLibraryService

router = APIRouter(prefix="/documents", tags=["documents"])
DocumentLibraryServiceDependency = Annotated[
    DocumentLibraryService, Depends(get_document_library_service)
]
CurrentUser = Annotated[AuthorizationContext, Depends(get_current_user)]


@router.get("", response_model=DocumentLibraryDTO, responses=AUTH_ERROR_RESPONSES)
async def list_documents(
    current_user: CurrentUser,
    service: DocumentLibraryServiceDependency,
    department_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DocumentLibraryDTO:
    """List documents only after applying tenant and department authorization."""
    library = await service.list_documents(current_user, department_id, limit)
    return DocumentLibraryDTO(
        documents=[
            DocumentDTO(
                document_id=document.document_id,
                title=document.title,
                departments=[
                    DepartmentDTO(department_id=department.department_id, name=department.name)
                    for department in document.departments
                ],
                current_ready_version_id=document.current_ready_version_id,
                latest_version=(
                    None
                    if document.latest_version is None
                    else DocumentVersionDTO(
                        document_version_id=document.latest_version.document_version_id,
                        version_number=document.latest_version.version_number,
                        original_filename=document.latest_version.original_filename,
                        status=document.latest_version.status,
                        created_at=document.latest_version.created_at,
                    )
                ),
                versions=[
                    DocumentVersionDTO(
                        document_version_id=version.document_version_id,
                        version_number=version.version_number,
                        original_filename=version.original_filename,
                        status=version.status,
                        created_at=version.created_at,
                    )
                    for version in document.versions
                ],
                created_at=document.created_at,
            )
            for document in library.documents
        ],
        departments=[
            DepartmentDTO(department_id=department.department_id, name=department.name)
            for department in library.departments
        ],
    )


@router.post("/{document_id}/activate", response_model=ActivatedDocumentVersionDTO)
async def activate_document_version(
    document_id: UUID,
    request: ActivateDocumentVersionRequest,
    current_user: CurrentUser,
    service: DocumentLibraryServiceDependency,
) -> ActivatedDocumentVersionDTO:
    """Atomically activate one ready version; this never starts or alters processing."""
    await service.activate_version(document_id, request.document_version_id, current_user)
    return ActivatedDocumentVersionDTO(
        document_id=document_id,
        current_ready_version_id=request.document_version_id,
    )
