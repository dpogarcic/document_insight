"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from document_insight import __version__
from document_insight.api.exception_handlers import register_exception_handlers
from document_insight.api.logging_config import configure_server_logging
from document_insight.api.middleware.correlation_id import CorrelationIdMiddleware
from document_insight.api.routes import api_router
from document_insight.config import get_settings
from document_insight.infrastructure.database import model_registry as _model_registry  # noqa: F401


def create_app() -> FastAPI:
    """Create the public API application without initializing infrastructure services."""
    configure_server_logging()
    application = FastAPI(
        title="Document Insight API",
        summary="Secure document ingestion and evidence-grounded question answering.",
        version=__version__,
    )
    settings = get_settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
    )
    register_exception_handlers(application)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(api_router)
    return application


app = create_app()
