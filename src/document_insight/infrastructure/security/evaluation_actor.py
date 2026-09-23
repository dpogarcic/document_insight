"""Resolve current evaluation identities within one selected tenant."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.evaluation.executor import EvaluationActorLoader
from document_insight.infrastructure.user.protocol import UserRepository
from document_insight.infrastructure.user_department.protocol import UserDepartmentRepository


class SqlAlchemyEvaluationActorLoader(EvaluationActorLoader):
    """Bind RLS before identity lookup and reject identities outside the selected tenant."""

    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        memberships: UserDepartmentRepository,
        evaluation_tenant_id: UUID,
    ) -> None:
        self._session = session
        self._users = users
        self._memberships = memberships
        self._tenant_id = evaluation_tenant_id

    async def load(self, user_id: UUID) -> AuthorizationContext:
        """Return current membership only after the database applies actor RLS."""
        if self._session.in_transaction():
            await self._session.rollback()
        self._session.info["rls_actor_id"] = user_id
        user = await self._users.get_by_id(user_id)
        if user is None or user.tenant_id != self._tenant_id:
            raise ValueError("Evaluation identity is not approved for this tenant")
        departments = await self._memberships.list_department_ids(user_id, user.tenant_id)
        if not departments:
            raise ValueError("Evaluation identity has no current department membership")
        return AuthorizationContext(user_id, user.tenant_id, departments, user.role)
