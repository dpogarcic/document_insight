"""One-time identity provisioning for the seeded evaluation tenant."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from document_insight.application.auth.models import UserRole
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.security.password_hasher import PasswordHasher
from document_insight.infrastructure.user.protocol import UserRepository
from document_insight.infrastructure.user_department.protocol import UserDepartmentRepository


class EvaluationIdentityAlreadyProvisionedError(Exception):
    """The seeded evaluation tenant already has an identity."""


class EvaluationTenantUnavailableError(Exception):
    """The evaluation tenant has no seeded department to assign."""


@dataclass(frozen=True, slots=True)
class EvaluationIdentityProvisioner:
    """Create only the first test-tenant admin under the auth database role."""

    users: UserRepository
    departments: DepartmentRepository
    memberships: UserDepartmentRepository
    transactions: TransactionManager
    passwords: PasswordHasher

    async def provision(
        self,
        tenant_id: UUID,
        email: str,
        display_name: str,
        password: str,
    ) -> UUID:
        """Create the initial admin and its department memberships atomically."""
        password_hash = await asyncio.to_thread(self.passwords.hash, password)
        async with self.transactions.begin():
            if await self.users.has_for_tenant(tenant_id):
                raise EvaluationIdentityAlreadyProvisionedError
            department_ids = await self.departments.list_all_ids(tenant_id)
            if not department_ids:
                raise EvaluationTenantUnavailableError
            user = await self.users.create(
                tenant_id,
                email.strip().lower(),
                display_name.strip(),
                password_hash,
                UserRole.TENANT_ADMIN,
            )
            for department_id in department_ids:
                await self.memberships.add(user.user_id, department_id, tenant_id)
            return user.user_id
