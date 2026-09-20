"""Stable API error contracts and helpers."""

from typing import Any, NoReturn

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict


class ErrorDetailDTO(BaseModel):
    """Machine-readable API error details."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorDTO(BaseModel):
    """FastAPI error envelope."""

    model_config = ConfigDict(extra="forbid")

    detail: ErrorDetailDTO


def raise_not_implemented(operation: str) -> NoReturn:
    """Raise a stable placeholder error for an API contract without an application service."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "not_implemented",
            "message": f"{operation} is not connected to an application service yet.",
        },
    )


# FastAPI models arbitrary OpenAPI metadata values with Any at this framework boundary.
NOT_IMPLEMENTED_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_501_NOT_IMPLEMENTED: {
        "model": ErrorDTO,
        "description": "The endpoint contract exists, but its application service is not implemented.",
    }
}

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorDTO,
        "description": "The supplied credentials are invalid.",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorDTO,
        "description": "The email address is already registered.",
    },
}

JOB_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorDTO,
        "description": "A valid bearer access token is required.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorDTO,
        "description": "The job does not exist within the caller's authorization scope.",
    },
}


def raise_api_error(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> NoReturn:
    """Raise a stable public API error without exposing infrastructure details."""
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers=headers,
    )
