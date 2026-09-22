"""SQLAlchemy adapter for authorized processing-job status reads."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.jobs.models import JobRecord, JobStatus, ProcessingJob, RequeueJob
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
                JobModel.status == JobStatus.QUEUED.value,
            )
            .values(
                status=JobStatus.PROCESSING.value,
                started_at=started_at,
                next_retry_at=None,
                attempt_count=JobModel.attempt_count + 1,
            )
            .returning(
                JobModel.id,
                JobModel.tenant_id,
                JobModel.document_version_id,
                JobModel.correlation_id,
                JobModel.ingestion_profile_id,
                JobModel.index_generation_id,
                JobModel.attempt_count,
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
            attempt_count=row.attempt_count,
        )

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        finished_at: datetime,
        error_category: str = "permanent",
        failure_reason: str | None = None,
    ) -> None:
        """Persist a safe terminal parser error without exception details."""
        await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id)
            .values(
                status=JobStatus.FAILED.value,
                error_code=error_code,
                finished_at=finished_at,
                error_category=error_category,
                failure_reason=failure_reason,
            )
        )

    async def mark_ready(self, job_id: UUID, finished_at: datetime) -> None:
        """Record successful end-to-end processing without queue-only state."""
        await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id)
            .values(status=JobStatus.READY.value, error_code=None, finished_at=finished_at)
        )

    async def retry(
        self,
        job_id: UUID,
        attempt_count: int,
        next_retry_at: datetime,
        error_category: str = "transient",
    ) -> None:
        """Schedule a transient failure for retry with exponential backoff.

        Sets the job back to queued state with retry timing metadata so the
        reconciliation process or a scheduled retry can resume it.
        """
        await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id)
            .values(
                status=JobStatus.QUEUED.value,
                attempt_count=attempt_count,
                error_category=error_category,
                next_retry_at=next_retry_at,
                last_attempt_at=datetime.now(UTC),
            )
        )

    async def list_requeue_candidates(
        self, now: datetime, stale_before: datetime, max_attempts: int, limit: int
    ) -> tuple[RequeueJob, ...]:
        """Find bounded transient or orphaned work without trusting Redis state."""
        recoverable = or_(
            and_(
                JobModel.status == JobStatus.QUEUED.value,
                or_(
                    JobModel.enqueued_at.is_(None),
                    JobModel.next_retry_at <= now,
                    JobModel.enqueued_at <= stale_before,
                ),
            ),
            and_(
                JobModel.status == JobStatus.PROCESSING.value,
                JobModel.started_at <= stale_before,
                JobModel.attempt_count < max_attempts,
            ),
            and_(
                JobModel.status == JobStatus.FAILED.value,
                JobModel.error_category == "transient",
                JobModel.attempt_count < max_attempts,
            ),
        )
        rows = (
            await self._session.execute(
                select(
                    JobModel.id,
                    JobModel.correlation_id,
                    JobModel.document_version_id,
                )
                .where(recoverable)
                .order_by(JobModel.created_at)
                .limit(limit)
            )
        ).all()
        return tuple(
            RequeueJob(row.id, row.correlation_id, row.document_version_id) for row in rows
        )

    async def prepare_for_requeue(
        self, job_id: UUID, now: datetime, stale_before: datetime, max_attempts: int
    ) -> RequeueJob | None:
        """Claim recovery responsibility before publishing to Redis again."""
        recoverable = or_(
            and_(
                JobModel.status == JobStatus.QUEUED.value,
                or_(
                    JobModel.enqueued_at.is_(None),
                    JobModel.next_retry_at <= now,
                    JobModel.enqueued_at <= stale_before,
                ),
            ),
            and_(
                JobModel.status == JobStatus.PROCESSING.value,
                JobModel.started_at <= stale_before,
                JobModel.attempt_count < max_attempts,
            ),
            and_(
                JobModel.status == JobStatus.FAILED.value,
                JobModel.error_category == "transient",
                JobModel.attempt_count < max_attempts,
            ),
        )
        result = await self._session.execute(
            update(JobModel)
            .where(JobModel.id == job_id, recoverable)
            .values(
                status=JobStatus.QUEUED.value,
                enqueued_at=None,
                next_retry_at=None,
                finished_at=None,
            )
            .returning(JobModel.id, JobModel.correlation_id, JobModel.document_version_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return RequeueJob(row.id, row.correlation_id, row.document_version_id)

    async def fail_stale_exhausted(
        self, now: datetime, stale_before: datetime, max_attempts: int
    ) -> tuple[UUID, ...]:
        """Make exhausted stale workers terminal instead of leaving them processing forever."""
        result = await self._session.execute(
            update(JobModel)
            .where(
                JobModel.status == JobStatus.PROCESSING.value,
                JobModel.started_at <= stale_before,
                JobModel.attempt_count >= max_attempts,
            )
            .values(
                status=JobStatus.FAILED.value,
                error_code="max_attempts_reached",
                error_category="permanent",
                failure_reason="stale_processing_exhausted",
                finished_at=now,
            )
            .returning(JobModel.document_version_id)
        )
        return tuple(row.document_version_id for row in result)
