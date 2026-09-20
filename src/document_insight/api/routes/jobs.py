"""Authorized processing-job status endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from document_insight.api.dependencies import get_current_user, get_job_service
from document_insight.api.errors import JOB_ERROR_RESPONSES
from document_insight.api.schemas.jobs import JobDTO
from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.jobs.service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
JobServiceDependency = Annotated[JobService, Depends(get_job_service)]
CurrentUser = Annotated[AuthorizationContext, Depends(get_current_user)]


@router.get(
    "/{job_id}",
    response_model=JobDTO,
    responses=JOB_ERROR_RESPONSES,
)
async def get_job(
    job_id: UUID,
    current_user: CurrentUser,
    service: JobServiceDependency,
) -> JobDTO:
    """Return the authoritative state of one authorized processing job."""
    job = await service.get_job(job_id, current_user)
    return JobDTO(
        job_id=job.job_id,
        document_id=job.document_id,
        document_version_id=job.document_version_id,
        status=job.status,
        attempt_count=job.attempt_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error_code=job.error_code,
    )
