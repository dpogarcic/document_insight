"""Application service for an authorization-safe document library."""

from uuid import UUID

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.documents.exceptions import (
    DocumentActivationForbiddenError,
    DocumentVersionNotReadyError,
)
from document_insight.application.documents.models import (
    DocumentLibrary,
    LibraryDepartment,
    LibraryDocument,
    LibraryVersion,
)
from document_insight.application.ingestion.exceptions import DocumentNotFoundError
from document_insight.application.ingestion.models import DocumentVersionStatus
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.document.protocol import DocumentRepository
from document_insight.infrastructure.document_department.protocol import (
    DocumentDepartmentRepository,
)
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository


class DocumentLibraryService:
    """Assemble document-library data after enforcing the caller's department scope."""

    def __init__(
        self,
        documents: DocumentRepository,
        departments: DepartmentRepository,
        document_departments: DocumentDepartmentRepository,
        document_versions: DocumentVersionRepository,
        transactions: TransactionManager,
    ) -> None:
        self._documents = documents
        self._departments = departments
        self._document_departments = document_departments
        self._document_versions = document_versions
        self._transactions = transactions

    async def activate_version(
        self,
        document_id: UUID,
        document_version_id: UUID,
        actor: AuthorizationContext,
    ) -> None:
        """Atomically select one ready version as the logical document's searchable version."""
        if actor.role is not UserRole.TENANT_ADMIN:
            raise DocumentActivationForbiddenError
        async with self._transactions.begin():
            if not await self._documents.lock(document_id, actor.tenant_id):
                raise DocumentNotFoundError
            candidate = await self._document_versions.get_for_activation(
                document_version_id,
                actor.tenant_id,
            )
            if candidate is None or candidate.document_id != document_id:
                raise DocumentNotFoundError
            if candidate.status is not DocumentVersionStatus.READY:
                raise DocumentVersionNotReadyError
            await self._documents.set_current_ready_version_id(
                document_id,
                actor.tenant_id,
                document_version_id,
            )

    async def list_documents(
        self,
        actor: AuthorizationContext,
        department_id: UUID | None,
        limit: int,
    ) -> DocumentLibrary:
        """Return only documents whose department assignments intersect the caller's scope."""
        available_department_ids = await self._available_department_ids(actor)
        available_departments = await self._departments.list_by_ids(
            actor.tenant_id,
            available_department_ids,
        )
        library_departments = tuple(
            LibraryDepartment(department_id=item.department_id, name=item.name)
            for item in available_departments
        )
        if department_id is not None and department_id not in set(available_department_ids):
            return DocumentLibrary(documents=(), departments=library_departments)

        candidates = await self._documents.list_for_tenant(actor.tenant_id)
        candidate_ids = tuple(candidate.document_id for candidate in candidates)
        assignments = await self._document_departments.list_for_document_ids(
            candidate_ids,
            actor.tenant_id,
        )
        department_ids_by_document: dict[UUID, set[UUID]] = {}
        for assignment in assignments:
            department_ids_by_document.setdefault(assignment.document_id, set()).add(
                assignment.department_id
            )

        permitted_ids = set(available_department_ids)
        visible_candidates = tuple(
            candidate
            for candidate in candidates
            if department_ids_by_document.get(candidate.document_id, set()) & permitted_ids
            and (
                department_id is None
                or department_id in department_ids_by_document[candidate.document_id]
            )
        )[:limit]
        visible_ids = tuple(candidate.document_id for candidate in visible_candidates)
        latest_by_document = {
            version.document_id: version
            for version in await self._document_versions.list_latest_for_document_ids(
                visible_ids,
                actor.tenant_id,
            )
        }
        versions_by_document: dict[UUID, list[LibraryVersion]] = {}
        for version in await self._document_versions.list_for_document_ids(
            visible_ids,
            actor.tenant_id,
        ):
            versions_by_document.setdefault(version.document_id, []).append(
                LibraryVersion(
                    document_version_id=version.document_version_id,
                    version_number=version.version_number,
                    original_filename=version.original_filename,
                    status=version.status,
                    created_at=version.created_at,
                )
            )
        department_by_id = {item.department_id: item for item in library_departments}
        return DocumentLibrary(
            documents=tuple(
                LibraryDocument(
                    document_id=candidate.document_id,
                    title=candidate.title,
                    departments=tuple(
                        department_by_id[assigned_id]
                        for assigned_id in sorted(
                            department_ids_by_document[candidate.document_id], key=str
                        )
                        if assigned_id in department_by_id
                    ),
                    current_ready_version_id=candidate.current_ready_version_id,
                    latest_version=(
                        None
                        if (latest := latest_by_document.get(candidate.document_id)) is None
                        else LibraryVersion(
                            document_version_id=latest.document_version_id,
                            version_number=latest.version_number,
                            original_filename=latest.original_filename,
                            status=latest.status,
                            created_at=latest.created_at,
                        )
                    ),
                    versions=tuple(versions_by_document.get(candidate.document_id, [])),
                    created_at=candidate.created_at,
                )
                for candidate in visible_candidates
            ),
            departments=library_departments,
        )

    async def _available_department_ids(self, actor: AuthorizationContext) -> tuple[UUID, ...]:
        """Resolve the tenant-wide or membership-scoped department set for the caller."""
        if actor.role is UserRole.TENANT_ADMIN:
            return await self._departments.list_all_ids(actor.tenant_id)
        return actor.department_ids
