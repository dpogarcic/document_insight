"""Application service for authorized processing-job status queries."""

from uuid import UUID

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.jobs.exceptions import JobNotFoundError
from document_insight.application.jobs.models import Job
from document_insight.infrastructure.document_department.protocol import (
    DocumentDepartmentRepository,
)
from document_insight.infrastructure.document_version.protocol import (
    DocumentVersionRepository,
)
from document_insight.infrastructure.job.protocol import JobRepository


class JobService:
    """Expose processing state without leaking cross-tenant or department jobs."""

    def __init__(
        self,
        jobs: JobRepository,
        document_versions: DocumentVersionRepository,
        document_departments: DocumentDepartmentRepository,
    ) -> None:
        self._jobs = jobs
        self._document_versions = document_versions
        self._document_departments = document_departments

    async def get_job(self, job_id: UUID, actor: AuthorizationContext) -> Job:
        """Load one job through the caller's mandatory authorization scope."""
        job = await self._jobs.get(job_id, actor.tenant_id)
        if job is None:
            raise JobNotFoundError

        document_id = await self._document_versions.get_document_id(
            job.document_version_id,
            actor.tenant_id,
        )
        if document_id is None:
            raise JobNotFoundError

        if actor.role is not UserRole.TENANT_ADMIN:
            department_ids = await self._document_departments.list_department_ids(
                document_id,
                actor.tenant_id,
            )
            if not set(department_ids) & set(actor.department_ids):
                raise JobNotFoundError

        return Job(
            job_id=job.job_id,
            document_id=document_id,
            document_version_id=job.document_version_id,
            status=job.status,
            attempt_count=job.attempt_count,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_code=job.error_code,
        )
