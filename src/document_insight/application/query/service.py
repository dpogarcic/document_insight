"""Prepare, but do not execute, an authorization-safe retrieval request."""

from uuid import UUID

from document_insight.application.auth.models import UserRole
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.exceptions import QueryProfileUnavailableError
from document_insight.application.query.models import AuthorizedRetrievalRequest
from document_insight.infrastructure.active_profile.protocol import ActiveProfileRepository
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.query_profile.protocol import QueryProfileRepository


class QueryPreparationService:
    """Resolve immutable query configuration and authorization before retrieval starts."""

    def __init__(
        self,
        active_profiles: ActiveProfileRepository,
        query_profiles: QueryProfileRepository,
        departments: DepartmentRepository,
    ) -> None:
        self._active_profiles = active_profiles
        self._query_profiles = query_profiles
        self._departments = departments

    async def prepare(self, command: PrepareQueryCommand) -> AuthorizedRetrievalRequest:
        """Build an authorization-bounded request without reading chunks or invoking models."""
        query_profile_id = await self._active_profiles.get_query_profile_id("platform")
        if query_profile_id is None:
            raise QueryProfileUnavailableError
        profile = await self._query_profiles.get(query_profile_id)
        if profile is None:
            raise QueryProfileUnavailableError
        authorized_departments = await self._authorized_departments(command)
        return AuthorizedRetrievalRequest(
            question=command.question,
            query_profile_id=profile.query_profile_id,
            lexical_profile_ids=profile.lexical_profile_ids,
            embedding_profile_ids=profile.embedding_profile_ids,
            tenant_id=command.actor.tenant_id,
            department_ids=authorized_departments,
            filter_text=command.filter_text,
            top_k=command.top_k,
        )

    async def _authorized_departments(self, command: PrepareQueryCommand) -> tuple[UUID, ...]:
        """Resolve tenant-admin scope or retain a non-admin's trusted token scope."""
        if command.actor.role is UserRole.TENANT_ADMIN:
            return await self._departments.list_all_ids(command.actor.tenant_id)
        return command.actor.department_ids
