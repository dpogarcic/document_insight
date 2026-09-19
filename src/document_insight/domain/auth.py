"""Authentication and membership domain types."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    """Roles supported by the first local-identity release."""

    TENANT_ADMIN = "tenant_admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class RegisteredUser:
    """Public result of provisioning a user and tenant membership."""

    user_id: UUID
    tenant_id: UUID
    department_id: UUID
    email: str
    display_name: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class StoredUser(RegisteredUser):
    """Authentication data loaded from persistence."""

    password_hash: str


@dataclass(frozen=True, slots=True)
class AccessToken:
    """Issued access token and its lifetime in seconds."""

    value: str
    expires_in: int
