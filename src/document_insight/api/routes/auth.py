"""Local registration and login endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from document_insight.api.dependencies import get_auth_service
from document_insight.api.errors import AUTH_ERROR_RESPONSES
from document_insight.api.schemas.auth import (
    AccessTokenDTO,
    LoginRequest,
    RegisterRequest,
    UserDTO,
)
from document_insight.application.auth.commands import RegisterUserCommand
from document_insight.application.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    response_model=UserDTO,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: AUTH_ERROR_RESPONSES[status.HTTP_409_CONFLICT]},
)
async def register_user(
    request: RegisterRequest,
    service: AuthServiceDependency,
) -> UserDTO:
    """Provision a new tenant, General department, and tenant administrator."""
    command = RegisterUserCommand(
        email=str(request.email),
        password=request.password,
        display_name=request.display_name,
        tenant_name=request.tenant_name,
    )
    user = await service.register(command)

    return UserDTO(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        department_ids=list(user.department_ids),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post(
    "/login",
    response_model=AccessTokenDTO,
    responses={status.HTTP_401_UNAUTHORIZED: AUTH_ERROR_RESPONSES[status.HTTP_401_UNAUTHORIZED]},
)
async def login(
    request: LoginRequest,
    service: AuthServiceDependency,
) -> AccessTokenDTO:
    """Authenticate a local user and return a short-lived bearer token."""
    token = await service.login(str(request.email), request.password)

    return AccessTokenDTO(access_token=token.value, expires_in=token.expires_in)
