"""User repository protocol."""

from typing import Protocol
from uuid import UUID

from document_insight.application.auth.models import UserRecord, UserRole


class UserRepository(Protocol):
    """Persistence operations owned by users."""

    async def has_for_tenant(self, tenant_id: UUID) -> bool:
        """Whether any identity already belongs to this tenant."""

    async def create(
        self,
        tenant_id: UUID,
        email: str,
        display_name: str,
        password_hash: str,
        role: UserRole,
    ) -> UserRecord:
        """Create and flush one local user."""

    async def get_by_email(self, email: str) -> UserRecord | None:
        """Load one local user without membership data."""

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        """Load one user under the current transaction's authorization scope."""
