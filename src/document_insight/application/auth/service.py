"""Local registration and login orchestration."""

import asyncio

from document_insight.application.auth.commands import RegisterUserCommand
from document_insight.application.auth.exceptions import InvalidCredentialsError
from document_insight.application.auth.models import (
    AccessToken,
    RegistrationResult,
    UserCredentials,
    UserRole,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.security.password_hasher import PasswordHasher
from document_insight.infrastructure.security.token_issuer import TokenIssuer
from document_insight.infrastructure.tenant.protocol import TenantRepository
from document_insight.infrastructure.user.protocol import UserRepository
from document_insight.infrastructure.user_department.protocol import UserDepartmentRepository


class AuthService:
    """Coordinate registration and login without depending on framework or vendor SDKs."""

    def __init__(
        self,
        tenants: TenantRepository,
        departments: DepartmentRepository,
        users: UserRepository,
        user_departments: UserDepartmentRepository,
        transactions: TransactionManager,
        password_hasher: PasswordHasher,
        token_issuer: TokenIssuer,
    ) -> None:
        self._tenants = tenants
        self._departments = departments
        self._users = users
        self._user_departments = user_departments
        self._transactions = transactions
        self._password_hasher = password_hasher
        self._token_issuer = token_issuer

    async def register(self, command: RegisterUserCommand) -> RegistrationResult:
        """Hash credentials and provision a new tenant administrator."""
        password_hash = await asyncio.to_thread(self._password_hasher.hash, command.password)
        normalized_email = command.email.strip().lower()
        async with self._transactions.begin():
            tenant_id = await self._tenants.create(command.tenant_name.strip())
            department_id = await self._departments.create(tenant_id, "General")
            user = await self._users.create(
                tenant_id=tenant_id,
                email=normalized_email,
                display_name=command.display_name.strip(),
                password_hash=password_hash,
                role=UserRole.TENANT_ADMIN,
            )
            await self._user_departments.add(user.user_id, department_id, tenant_id)

        return RegistrationResult(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            department_ids=(department_id,),
            email=user.email,
            display_name=user.display_name,
            role=user.role,
        )

    async def login(self, email: str, password: str) -> AccessToken:
        """Authenticate credentials and issue a short-lived access token."""
        normalized_email = email.strip().lower()
        persisted_user = await self._users.get_by_email(normalized_email)
        if persisted_user is None:
            await asyncio.to_thread(self._password_hasher.verify_unknown_user, password)
            raise InvalidCredentialsError

        is_valid = await asyncio.to_thread(
            self._password_hasher.verify,
            password,
            persisted_user.password_hash,
        )
        if not is_valid:
            raise InvalidCredentialsError

        department_ids = await self._user_departments.list_department_ids(
            persisted_user.user_id,
            persisted_user.tenant_id,
        )
        user = UserCredentials(
            user_id=persisted_user.user_id,
            tenant_id=persisted_user.tenant_id,
            department_ids=department_ids,
            email=persisted_user.email,
            display_name=persisted_user.display_name,
            role=persisted_user.role,
            password_hash=persisted_user.password_hash,
        )
        return self._token_issuer.issue(user)
