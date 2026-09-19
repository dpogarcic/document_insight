"""Ports and commands used by the authentication application service."""

from dataclasses import dataclass
from typing import Protocol

from document_insight.domain.auth import AccessToken, RegisteredUser, StoredUser


@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    """Validated data used to provision a new tenant administrator."""

    email: str
    password: str
    display_name: str
    tenant_name: str


class AuthRepository(Protocol):
    """Persistence operations required by local authentication."""

    async def create_tenant_admin(
        self,
        command: RegisterUserCommand,
        password_hash: str,
    ) -> RegisteredUser:
        """Atomically create a tenant, initial department, and administrator."""

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        """Load credentials and membership claims for an email address."""


class PasswordHasher(Protocol):
    """Password hashing operations isolated from the application service."""

    def hash(self, password: str) -> str:
        """Create a password hash suitable for persistent storage."""

    def verify(self, password: str, password_hash: str) -> bool:
        """Verify a password against a stored hash."""

    def verify_unknown_user(self, password: str) -> None:
        """Perform equivalent work when the requested user does not exist."""


class TokenIssuer(Protocol):
    """Access-token operations required by login."""

    def issue(self, user: StoredUser) -> AccessToken:
        """Issue a signed access token for an authenticated user."""
