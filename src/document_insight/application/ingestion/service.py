"""Application workflow for validating and storing document originals."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.ingestion.commands import IngestDocumentCommand
from document_insight.application.ingestion.exceptions import (
    DocumentNotFoundError,
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionForbiddenError,
    InvalidDepartmentScopeError,
    UnsupportedDocumentTypeError,
)
from document_insight.application.ingestion.models import (
    DocumentMediaType,
    IngestionResult,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.document.protocol import DocumentRepository
from document_insight.infrastructure.document_department.protocol import (
    DocumentDepartmentRepository,
)
from document_insight.infrastructure.document_version.protocol import (
    CreateDocumentVersion,
    DocumentVersionRepository,
)
from document_insight.infrastructure.job.protocol import CreateJob, JobRepository
from document_insight.infrastructure.object_storage.protocol import OriginalObjectStorage
from document_insight.infrastructure.queue.protocol import ProcessingQueue

_SIGNATURES = {
    DocumentMediaType.PDF: (b"%PDF-", ".pdf"),
    DocumentMediaType.PNG: (b"\x89PNG\r\n\x1a\n", ".png"),
    DocumentMediaType.JPEG: (b"\xff\xd8\xff", ".jpg"),
}


class IngestionService:
    """Validate, authorize, and persist an immutable original document."""

    def __init__(
        self,
        documents: DocumentRepository,
        departments: DepartmentRepository,
        document_departments: DocumentDepartmentRepository,
        document_versions: DocumentVersionRepository,
        jobs: JobRepository,
        transactions: TransactionManager,
        object_storage: OriginalObjectStorage,
        processing_queue: ProcessingQueue,
        max_upload_bytes: int,
    ) -> None:
        self._documents = documents
        self._departments = departments
        self._document_departments = document_departments
        self._document_versions = document_versions
        self._jobs = jobs
        self._transactions = transactions
        self._object_storage = object_storage
        self._processing_queue = processing_queue
        self._max_upload_bytes = max_upload_bytes

    async def ingest(self, command: IngestDocumentCommand) -> IngestionResult:
        """Store an upload and persist its metadata, compensating on database failure."""
        if command.actor.role is UserRole.VIEWER:
            raise IngestionForbiddenError
        if not command.content:
            raise EmptyDocumentError
        if len(command.content) > self._max_upload_bytes:
            raise DocumentTooLargeError

        media_type, suffix = self._detect_media_type(
            command.content,
            command.declared_content_type,
        )
        async with self._transactions.begin():
            effective_departments = await self._resolve_departments(command)

        document_id = command.document_id or uuid4()
        version_id = uuid4()
        job_id = uuid4()
        idempotency_key = uuid4()
        object_key = (
            f"tenants/{command.actor.tenant_id}/documents/{document_id}/"
            f"versions/{version_id}/original{suffix}"
        )
        await self._object_storage.put(object_key, command.content, media_type.value)

        original_filename = Path(command.filename).name or f"document{suffix}"
        content_sha256 = sha256(command.content).hexdigest()
        try:
            async with self._transactions.begin():
                if command.document_id is None:
                    await self._documents.create(
                        document_id=document_id,
                        tenant_id=command.actor.tenant_id,
                        title=original_filename,
                        created_by=command.actor.user_id,
                    )
                    await self._document_departments.add_many(
                        document_id,
                        command.actor.tenant_id,
                        effective_departments,
                    )
                    version_number = 1
                else:
                    if not await self._documents.lock(document_id, command.actor.tenant_id):
                        raise DocumentNotFoundError
                    effective_departments = await self._authorize_existing_document(
                        document_id,
                        command.actor,
                    )
                    version_number = await self._document_versions.next_version_number(document_id)

                await self._document_versions.create(
                    CreateDocumentVersion(
                        document_id=document_id,
                        document_version_id=version_id,
                        tenant_id=command.actor.tenant_id,
                        version_number=version_number,
                        original_filename=original_filename,
                        object_key=object_key,
                        media_type=media_type,
                        size_bytes=len(command.content),
                        content_sha256=content_sha256,
                        created_by=command.actor.user_id,
                    )
                )
                await self._jobs.create(
                    CreateJob(
                        job_id=job_id,
                        tenant_id=command.actor.tenant_id,
                        document_version_id=version_id,
                        idempotency_key=idempotency_key,
                        correlation_id=command.correlation_id,
                        created_by=command.actor.user_id,
                    )
                )
        except Exception:
            await self._object_storage.delete(object_key)
            raise

        await self._processing_queue.enqueue_ingestion(job_id, command.correlation_id)
        async with self._transactions.begin():
            await self._jobs.mark_enqueued(job_id, datetime.now(UTC))

        return IngestionResult(
            document_id=document_id,
            document_version_id=version_id,
            job_id=job_id,
            version_number=version_number,
            object_key=object_key,
            media_type=media_type,
            size_bytes=len(command.content),
            content_sha256=content_sha256,
        )

    async def _resolve_departments(self, command: IngestDocumentCommand) -> tuple[UUID, ...]:
        """Authorize the target and return its effective department assignments."""
        if command.document_id is not None:
            if not await self._documents.exists(command.document_id, command.actor.tenant_id):
                raise DocumentNotFoundError
            return await self._authorize_existing_document(command.document_id, command.actor)

        if command.actor.role is UserRole.EDITOR:
            effective_ids = command.department_ids or command.actor.department_ids
            unique_ids = tuple(dict.fromkeys(effective_ids))
            if not unique_ids or not set(unique_ids).issubset(command.actor.department_ids):
                raise InvalidDepartmentScopeError
            return unique_ids

        effective_ids = command.department_ids or command.actor.department_ids
        unique_ids = tuple(dict.fromkeys(effective_ids))
        matched_ids = await self._departments.existing_ids(
            command.actor.tenant_id,
            unique_ids,
        )
        if matched_ids != set(unique_ids):
            raise InvalidDepartmentScopeError
        return unique_ids

    async def _authorize_existing_document(
        self,
        document_id: UUID,
        actor: AuthorizationContext,
    ) -> tuple[UUID, ...]:
        departments = await self._document_departments.list_department_ids(
            document_id,
            actor.tenant_id,
        )
        if actor.role is not UserRole.TENANT_ADMIN and not (
            set(departments) & set(actor.department_ids)
        ):
            raise IngestionForbiddenError
        return departments

    @staticmethod
    def _detect_media_type(
        content: bytes, declared_content_type: str | None
    ) -> tuple[DocumentMediaType, str]:
        for media_type, (signature, suffix) in _SIGNATURES.items():
            if content.startswith(signature):
                if declared_content_type not in {None, "", media_type.value}:
                    raise UnsupportedDocumentTypeError
                return media_type, suffix
        raise UnsupportedDocumentTypeError
