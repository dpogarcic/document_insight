"""User repository protocol."""

from typing import Protocol
from uuid import UUID

from document_insight.application.auth.models import UserRecord, UserRole


class UserRepository(Protocol):
    """Persistence operations owned by users."""

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
