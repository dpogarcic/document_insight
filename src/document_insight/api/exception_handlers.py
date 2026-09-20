"""Application-wide translation of expected application errors into safe HTTP responses."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from document_insight.api.middleware.correlation_id import correlation_id_scope
from document_insight.application.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from document_insight.application.ingestion.exceptions import (
    DocumentNotFoundError,
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionForbiddenError,
    InvalidDepartmentScopeError,
    ObjectStorageUnavailableError,
    QueueUnavailableError,
    UnsupportedDocumentTypeError,
)
from document_insight.application.jobs.exceptions import JobNotFoundError

logger = logging.getLogger(__name__)


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the stable public error envelope used by domain exception handlers."""
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message}},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all expected domain-to-HTTP error translations on an application."""

    @app.exception_handler(EmailAlreadyRegisteredError)
    async def handle_email_already_registered(
        _: Request,
        __: Exception,
    ) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            "email_already_registered",
            "An account with this email address already exists.",
        )

    @app.exception_handler(InvalidCredentialsError)
    async def handle_invalid_credentials(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            "The email address or password is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(EmptyDocumentError)
    async def handle_empty_document(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "empty_document",
            "The uploaded document is empty.",
        )

    @app.exception_handler(DocumentTooLargeError)
    async def handle_document_too_large(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "document_too_large",
            "The uploaded document exceeds 25 MiB.",
        )

    @app.exception_handler(UnsupportedDocumentTypeError)
    async def handle_unsupported_document_type(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_document_type",
            "The upload must be a PDF, PNG, or JPEG with a matching file signature.",
        )

    @app.exception_handler(DocumentNotFoundError)
    async def handle_document_not_found(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "document_not_found",
            "The requested document was not found.",
        )

    @app.exception_handler(IngestionForbiddenError)
    @app.exception_handler(InvalidDepartmentScopeError)
    async def handle_ingestion_forbidden(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "ingestion_forbidden",
            "You cannot ingest this document.",
        )

    @app.exception_handler(ObjectStorageUnavailableError)
    async def handle_object_storage_unavailable(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "object_storage_unavailable",
            "Document storage is unavailable.",
        )

    @app.exception_handler(QueueUnavailableError)
    async def handle_queue_unavailable(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "queue_unavailable",
            "Document processing is temporarily unavailable. Please retry the upload.",
        )

    @app.exception_handler(JobNotFoundError)
    async def handle_job_not_found(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "job_not_found",
            "The requested job was not found.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        exception: Exception,
    ) -> JSONResponse:
        with correlation_id_scope(request.state.correlation_id):
            logger.error(
                "Unhandled application exception",
                extra={
                    "request_method": request.method,
                    "request_path": request.url.path,
                },
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_server_error",
            "An unexpected error occurred.",
            headers={"X-Correlation-ID": request.state.correlation_id},
        )
