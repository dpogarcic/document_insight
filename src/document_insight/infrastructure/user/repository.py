"""SQLAlchemy persistence adapter for users."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.application.auth.exceptions import EmailAlreadyRegisteredError
from document_insight.application.auth.models import UserRecord, UserRole
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user.protocol import UserRepository


class SqlAlchemyUserRepository(UserRepository):
    """Own persistence operations for local user records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_for_tenant(self, tenant_id: UUID) -> bool:
        """Check whether initial identity provisioning has already occurred."""
        identifier = await self._session.scalar(
            select(UserModel.id).where(UserModel.tenant_id == tenant_id).limit(1)
        )
        return identifier is not None

    async def create(
        self,
        tenant_id: UUID,
        email: str,
        display_name: str,
        password_hash: str,
        role: UserRole,
    ) -> UserRecord:
        """Create and flush one user, translating an email conflict safely."""
        user = UserModel(
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role.value,
        )
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise EmailAlreadyRegisteredError from error
        return self._to_record(user)

    async def get_by_email(self, email: str) -> UserRecord | None:
        """Load one user by normalized globally unique email address."""
        user = await self._session.scalar(select(UserModel).where(UserModel.email == email))
        return None if user is None else self._to_record(user)

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        """Load one user without joining other persisted entities."""
        user = await self._session.scalar(select(UserModel).where(UserModel.id == user_id))
        return None if user is None else self._to_record(user)

    @staticmethod
    def _to_record(user: UserModel) -> UserRecord:
        return UserRecord(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            display_name=user.display_name,
            role=UserRole(user.role),
            password_hash=user.password_hash,
        )
