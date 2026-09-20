"""Response schemas for processing-job endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from document_insight.api.schemas.common import ApiModel
from document_insight.application.jobs.models import JobStatus


class JobDTO(ApiModel):
    """Current processing state for an accepted document version."""

    job_id: UUID
    document_id: UUID
    document_version_id: UUID
    status: JobStatus
    attempt_count: Annotated[int, Field(ge=0)]
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
