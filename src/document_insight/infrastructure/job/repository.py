"""SQLAlchemy adapter for authorized processing-job status reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.jobs.models import JobRecord, JobStatus, ProcessingJob
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
                ingestion_profile_id=command.ingestion_profile_id,
                index_generation_id=command.index_generation_id,
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

    async def mark_enqueued(self, job_id: UUID, enqueued_at: datetime) -> None:
        """Persist the point at which RQ accepted a durable job."""
        await self._session.execute(
            update(JobModel).where(JobModel.id == job_id).values(enqueued_at=enqueued_at)
        )

    async def claim(self, job_id: UUID, started_at: datetime) -> ProcessingJob | None:
        """Claim queued or retried work; outputs remain idempotent by version."""
        result = await self._session.execute(
            update(JobModel)
            .where(
                JobModel.id == job_id,
                JobModel.status.in_((JobStatus.QUEUED.value, JobStatus.PROCESSING.value)),
            )
            .values(
                status=JobStatus.PROCESSING.value,
                started_at=started_at,
                attempt_count=JobModel.attempt_count + 1,
            )
            .returning(
                JobModel.id,
                JobModel.tenant_id,
                JobModel.document_version_id,
                JobModel.correlation_id,
                JobModel.ingestion_profile_id,
                JobModel.index_generation_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return ProcessingJob(
            job_id=row.id,
            tenant_id=row.tenant_id,
            document_version_id=row.document_version_id,
            correlation_id=row.correlation_id,
            ingestion_profile_id=row.ingestion_profile_id,
            index_generation_id=row.index_generation_id,
        )

    async def fail(self, job_id: UUID, error_code: str, finished_at: datetime) -> None:
        """Persist a safe terminal parser error without exception details."""
        await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id)
            .values(
                status=JobStatus.FAILED.value,
                error_code=error_code,
                finished_at=finished_at,
            )
        )

    async def mark_ready(self, job_id: UUID, finished_at: datetime) -> None:
        """Record successful end-to-end processing without queue-only state."""
        await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id)
            .values(status=JobStatus.READY.value, error_code=None, finished_at=finished_at)
        )
