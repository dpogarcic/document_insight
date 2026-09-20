"""Response schemas for the document ingestion endpoint."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from document_insight.api.schemas.common import ApiModel
from document_insight.application.ingestion.models import DocumentVersionStatus
from document_insight.application.jobs.models import JobStatus


class IngestStoredDTO(ApiModel):
    """Identifiers returned after the original and version metadata are stored."""

    document_id: UUID
    document_version_id: UUID
    job_id: UUID
    version_number: Annotated[int, Field(ge=1)]
    status: DocumentVersionStatus = DocumentVersionStatus.STORED
    job_status: JobStatus = JobStatus.QUEUED
