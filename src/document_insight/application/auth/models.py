"""Authentication and authorization models used by the application layer."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    """Roles supported by the first local-identity release."""

    TENANT_ADMIN = "tenant_admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Result of provisioning a tenant administrator and initial membership."""

    user_id: UUID
    tenant_id: UUID
    department_ids: tuple[UUID, ...]
    email: str
    display_name: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class UserRecord:
    """User data loaded from persistence without department memberships."""

    user_id: UUID
    tenant_id: UUID
    email: str
    display_name: str
    role: UserRole
    password_hash: str


@dataclass(frozen=True, slots=True)
class UserCredentials(RegistrationResult):
    """User data and password hash used only during local authentication."""

    password_hash: str


@dataclass(frozen=True, slots=True)
class AccessToken:
    """Issued access token and its lifetime in seconds."""

    value: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Trusted authorization claims extracted from a validated access token."""

    user_id: UUID
    tenant_id: UUID
    department_ids: tuple[UUID, ...]
    role: UserRole
