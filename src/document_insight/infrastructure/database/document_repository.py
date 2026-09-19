"""SQLAlchemy persistence adapter for documents and immutable versions."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.ingestion.contracts import StoreDocumentVersion
from document_insight.application.ingestion.exceptions import (
    DocumentNotFoundError,
    IngestionForbiddenError,
    InvalidDepartmentScopeError,
)
from document_insight.domain.auth import AuthenticatedUser, UserRole
from document_insight.domain.ingestion import StoredDocumentVersion
from document_insight.infrastructure.database.models import (
    DepartmentModel,
    DocumentDepartmentModel,
    DocumentModel,
    DocumentVersionModel,
)


class SqlAlchemyDocumentRepository:
    """Authorize document targets and persist storage-stage document metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate_upload_target(
        self,
        document_id: UUID | None,
        requested_department_ids: tuple[UUID, ...],
        actor: AuthenticatedUser,
    ) -> tuple[UUID, ...]:
        """Resolve a safe department set before writing the original object."""
        if document_id is not None:
            departments = await self._existing_document_departments(document_id, actor)
            await self._session.rollback()
            return departments

        if actor.role is UserRole.EDITOR:
            actor_departments = set(actor.department_ids)
            effective_ids = requested_department_ids or actor.department_ids
            unique_ids = tuple(dict.fromkeys(effective_ids))
            if not unique_ids or not set(unique_ids).issubset(actor_departments):
                raise InvalidDepartmentScopeError
            return unique_ids

        effective_ids = requested_department_ids or actor.department_ids
        unique_ids = tuple(dict.fromkeys(effective_ids))
        matched_ids = set(
            await self._session.scalars(
                select(DepartmentModel.id).where(
                    DepartmentModel.tenant_id == actor.tenant_id,
                    DepartmentModel.id.in_(unique_ids),
                )
            )
        )
        await self._session.rollback()
        if matched_ids != set(unique_ids):
            raise InvalidDepartmentScopeError
        return unique_ids

    async def create_stored_version(
        self,
        upload: StoreDocumentVersion,
        effective_department_ids: tuple[UUID, ...],
    ) -> StoredDocumentVersion:
        """Create document metadata and allocate the next version atomically."""
        async with self._session.begin():
            if upload.replaces_existing_document:
                document = await self._session.scalar(
                    select(DocumentModel)
                    .where(
                        DocumentModel.id == upload.document_id,
                        DocumentModel.tenant_id == upload.actor.tenant_id,
                    )
                    .with_for_update()
                )
                if document is None:
                    raise DocumentNotFoundError
                await self._assert_document_access(upload.document_id, upload.actor)
                version_number = (
                    await self._session.scalar(
                        select(func.max(DocumentVersionModel.version_number)).where(
                            DocumentVersionModel.document_id == upload.document_id
                        )
                    )
                    or 0
                ) + 1
            else:
                version_number = 1
                self._session.add(
                    DocumentModel(
                        id=upload.document_id,
                        tenant_id=upload.actor.tenant_id,
                        title=upload.filename,
                        created_by=upload.actor.user_id,
                    )
                )
                self._session.add_all(
                    DocumentDepartmentModel(
                        document_id=upload.document_id,
                        department_id=department_id,
                        tenant_id=upload.actor.tenant_id,
                    )
                    for department_id in effective_department_ids
                )

            self._session.add(
                DocumentVersionModel(
                    id=upload.document_version_id,
                    document_id=upload.document_id,
                    tenant_id=upload.actor.tenant_id,
                    version_number=version_number,
                    original_filename=upload.filename,
                    object_key=upload.object_key,
                    media_type=upload.media_type.value,
                    size_bytes=upload.size_bytes,
                    content_sha256=bytes.fromhex(upload.content_sha256),
                    status="stored",
                    created_by=upload.actor.user_id,
                )
            )

        return StoredDocumentVersion(
            document_id=upload.document_id,
            document_version_id=upload.document_version_id,
            version_number=version_number,
            object_key=upload.object_key,
            media_type=upload.media_type,
            size_bytes=upload.size_bytes,
            content_sha256=upload.content_sha256,
        )

    async def _existing_document_departments(
        self,
        document_id: UUID,
        actor: AuthenticatedUser,
    ) -> tuple[UUID, ...]:
        document_exists = await self._session.scalar(
            select(DocumentModel.id).where(
                DocumentModel.id == document_id,
                DocumentModel.tenant_id == actor.tenant_id,
            )
        )
        if document_exists is None:
            raise DocumentNotFoundError
        return await self._assert_document_access(document_id, actor)

    async def _assert_document_access(
        self,
        document_id: UUID,
        actor: AuthenticatedUser,
    ) -> tuple[UUID, ...]:
        departments = tuple(
            await self._session.scalars(
                select(DocumentDepartmentModel.department_id).where(
                    DocumentDepartmentModel.document_id == document_id,
                    DocumentDepartmentModel.tenant_id == actor.tenant_id,
                )
            )
        )
        if actor.role is not UserRole.TENANT_ADMIN and not (
            set(departments) & set(actor.department_ids)
        ):
            raise IngestionForbiddenError
        return departments
