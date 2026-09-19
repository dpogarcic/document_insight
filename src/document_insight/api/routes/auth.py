"""Local registration and login endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from document_insight.api.dependencies import get_auth_service
from document_insight.api.errors import AUTH_ERROR_RESPONSES, raise_api_error
from document_insight.api.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from document_insight.application.auth.contracts import RegisterUserCommand
from document_insight.application.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from document_insight.application.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: AUTH_ERROR_RESPONSES[status.HTTP_409_CONFLICT]},
)
async def register_user(request: RegisterRequest, service: AuthServiceDependency) -> UserResponse:
    """Provision a new tenant, General department, and tenant administrator."""
    command = RegisterUserCommand(
        email=str(request.email),
        password=request.password,
        display_name=request.display_name,
        tenant_name=request.tenant_name,
    )
    try:
        user = await service.register(command)
    except EmailAlreadyRegisteredError:
        raise_api_error(
            status.HTTP_409_CONFLICT,
            "email_already_registered",
            "An account with this email address already exists.",
        )

    return UserResponse(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        department_id=user.department_id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post(
    "/login",
    response_model=AccessTokenResponse,
    responses={status.HTTP_401_UNAUTHORIZED: AUTH_ERROR_RESPONSES[status.HTTP_401_UNAUTHORIZED]},
)
async def login(request: LoginRequest, service: AuthServiceDependency) -> AccessTokenResponse:
    """Authenticate a local user and return a short-lived bearer token."""
    try:
        token = await service.login(str(request.email), request.password)
    except InvalidCredentialsError:
        raise_api_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            "The email address or password is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AccessTokenResponse(access_token=token.value, expires_in=token.expires_in)
