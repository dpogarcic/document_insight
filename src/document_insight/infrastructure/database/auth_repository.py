"""SQLAlchemy persistence adapter for local authentication."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.auth.contracts import RegisterUserCommand
from document_insight.application.auth.exceptions import EmailAlreadyRegisteredError
from document_insight.domain.auth import RegisteredUser, StoredUser, UserRole
from document_insight.infrastructure.database.models import (
    DepartmentModel,
    TenantModel,
    UserDepartmentModel,
    UserModel,
)


class SqlAlchemyAuthRepository:
    """Persist and load authentication records through an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_tenant_admin(
        self,
        command: RegisterUserCommand,
        password_hash: str,
    ) -> RegisteredUser:
        """Atomically create a tenant, General department, and administrator."""
        normalized_email = command.email.strip().lower()
        try:
            async with self._session.begin():
                existing_id = await self._session.scalar(
                    select(UserModel.id).where(UserModel.email == normalized_email)
                )
                if existing_id is not None:
                    raise EmailAlreadyRegisteredError

                tenant = TenantModel(name=command.tenant_name.strip())
                self._session.add(tenant)
                await self._session.flush()

                department = DepartmentModel(tenant_id=tenant.id, name="General")
                self._session.add(department)
                await self._session.flush()

                user = UserModel(
                    tenant_id=tenant.id,
                    email=normalized_email,
                    display_name=command.display_name.strip(),
                    password_hash=password_hash,
                    role=UserRole.TENANT_ADMIN.value,
                )
                self._session.add(user)
                await self._session.flush()
                self._session.add(
                    UserDepartmentModel(
                        user_id=user.id,
                        department_id=department.id,
                        tenant_id=tenant.id,
                    )
                )
        except IntegrityError as error:
            raise EmailAlreadyRegisteredError from error

        return RegisteredUser(
            user_id=user.id,
            tenant_id=user.tenant_id,
            department_ids=(department.id,),
            email=user.email,
            display_name=user.display_name,
            role=UserRole(user.role),
        )

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        """Load one user by normalized globally unique email address."""
        user = await self._session.scalar(select(UserModel).where(UserModel.email == email))
        if user is None:
            return None
        department_ids = tuple(
            await self._session.scalars(
                select(UserDepartmentModel.department_id)
                .where(
                    UserDepartmentModel.user_id == user.id,
                    UserDepartmentModel.tenant_id == user.tenant_id,
                )
                .order_by(UserDepartmentModel.department_id)
            )
        )
        return StoredUser(
            user_id=user.id,
            tenant_id=user.tenant_id,
            department_ids=department_ids,
            email=user.email,
            display_name=user.display_name,
            role=UserRole(user.role),
            password_hash=user.password_hash,
        )
