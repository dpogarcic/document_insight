"""FastAPI application factory."""

from fastapi import FastAPI

from document_insight import __version__
from document_insight.api.routes import api_router


def create_app() -> FastAPI:
    """Create the public API application without initializing infrastructure services."""
    application = FastAPI(
        title="Document Insight API",
        summary="Secure document ingestion and evidence-grounded question answering.",
        version=__version__,
    )
    application.include_router(api_router)
    return application


app = create_app()
