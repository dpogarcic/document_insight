"""Request and response schemas for local authentication endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from document_insight.api.schemas.common import ApiModel
from document_insight.domain.auth import UserRole

Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class RegisterRequest(ApiModel):
    """Credentials and profile data needed to register a local user."""

    email: EmailStr
    password: Password
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    tenant_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]


class UserResponse(ApiModel):
    """Public representation of a registered user."""

    user_id: UUID
    tenant_id: UUID
    department_id: UUID
    email: EmailStr
    display_name: str
    role: UserRole


class LoginRequest(ApiModel):
    """Credentials used to obtain an access token."""

    email: EmailStr
    password: Password


class AccessTokenResponse(ApiModel):
    """Short-lived bearer token returned after successful authentication."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: Annotated[int, Field(gt=0)]
