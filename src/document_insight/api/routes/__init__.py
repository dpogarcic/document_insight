"""Composition root for public API routes."""

from fastapi import APIRouter

from document_insight.api.routes.auth import router as auth_router
from document_insight.api.routes.documents import router as documents_router
from document_insight.api.routes.ingest import router as ingest_router
from document_insight.api.routes.jobs import router as jobs_router
from document_insight.api.routes.query import router as query_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(ingest_router)
api_router.include_router(jobs_router)
api_router.include_router(query_router)
