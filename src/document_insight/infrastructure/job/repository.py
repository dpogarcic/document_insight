"""SQLAlchemy adapter for authorized processing-job status reads."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.jobs.models import JobRecord, JobStatus
from document_insight.infrastructure.job.model import JobModel
from document_insight.infrastructure.job.protocol import CreateJob, JobRepository


class SqlAlchemyJobRepository(JobRepository):
    """Own persistence operations for processing-job records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, command: CreateJob) -> None:
        """Create one durable job in its initial pre-publication state."""
        self._session.add(
            JobModel(
                id=command.job_id,
                tenant_id=command.tenant_id,
                document_version_id=command.document_version_id,
                idempotency_key=command.idempotency_key,
                correlation_id=command.correlation_id,
                status="queued",
                attempt_count=0,
                created_by=command.created_by,
            )
        )

    async def get(self, job_id: UUID, tenant_id: UUID) -> JobRecord | None:
        """Return one tenant-scoped job without joining another entity's table."""
        job = await self._session.scalar(
            select(JobModel).where(
                JobModel.id == job_id,
                JobModel.tenant_id == tenant_id,
            )
        )
        if job is None:
            return None
        return JobRecord(
            job_id=job.id,
            tenant_id=job.tenant_id,
            document_version_id=job.document_version_id,
            status=JobStatus(job.status),
            attempt_count=job.attempt_count,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_code=job.error_code,
        )
