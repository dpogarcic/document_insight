"""Separate, operator-authenticated FastAPI application for profile administration."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.admin_panel import views
from document_insight.application.configuration.approval import ProfileApprovalService
from document_insight.application.configuration.catalog import ProfileCatalogService
from document_insight.application.configuration.exceptions import (
    InvalidProfileProposalError,
    ProfileRevisionConflictError,
)
from document_insight.application.configuration.models import Capability
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.ingestion_profile.repository import (
    SqlAlchemyIngestionProfileRepository,
)
from document_insight.infrastructure.profile_activation.repository import (
    SqlAlchemyProfileActivationRepository,
)
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)

_BASIC = HTTPBasic(auto_error=False)
_CSRF_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_STATIC = Path(__file__).with_name("static")


@dataclass(frozen=True, slots=True)
class PanelServices:
    """One request's application services backed by the restricted operator session."""

    approval: ProfileApprovalService
    catalog: ProfileCatalogService


async def _operator_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session using only the profile-operator login."""
    async with get_session_factory("profile_operator")() as session:
        yield session


OperatorSession = Annotated[AsyncSession, Depends(_operator_session)]


def _services(request: Request, _: Operator, session: OperatorSession) -> PanelServices:
    """Compose business services without granting the panel document-data access."""
    settings: Settings = request.app.state.settings
    snapshots = SqlAlchemyConfigurationSnapshotRepository(session)
    capabilities = SqlAlchemyCapabilityProfileRepository(session)
    ingestions = SqlAlchemyIngestionProfileRepository(session)
    queries = SqlAlchemyQueryProfileRepository(session)
    active = SqlAlchemyActiveProfileRepository(session)
    return PanelServices(
        ProfileApprovalService(
            snapshots,
            capabilities,
            ingestions,
            queries,
            active,
            SqlAlchemyIndexGenerationRepository(session),
            SqlAlchemyProfileActivationRepository(session),
            SqlAlchemyTransactionManager(session),
            bool(settings.mistral_api_key and settings.mistral_api_key.get_secret_value()),
        ),
        ProfileCatalogService(capabilities, ingestions, queries, snapshots, active),
    )


Services = Annotated[PanelServices, Depends(_services)]


def _authenticate(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC)],
) -> str:
    """Use a dedicated operator password before any configuration database access."""
    settings: Settings = request.app.state.settings
    expected_password = settings.admin_panel_password
    if (
        credentials is None
        or expected_password is None
        or settings.admin_panel_username is None
        or not compare_digest(credentials.username, settings.admin_panel_username)
        or not compare_digest(credentials.password, expected_password.get_secret_value())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Document Insight Admin"'},
        )
    return credentials.username


Operator = Annotated[str, Depends(_authenticate)]


def _csrf(request: Request) -> tuple[str, bool]:
    """Return or mint a host-only CSRF token for browser form submission."""
    existing = getattr(request.state, "panel_csrf", None)
    if (
        isinstance(existing, tuple)
        and len(existing) == 2
        and isinstance(existing[0], str)
        and isinstance(existing[1], bool)
    ):
        return existing
    token = request.cookies.get("di_admin_csrf")
    if token is not None and _CSRF_PATTERN.fullmatch(token):
        result = (token, False)
    else:
        result = (secrets.token_urlsafe(32), True)
    request.state.panel_csrf = result
    return result


def _page(
    request: Request,
    title: str,
    body: str,
    *,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render an uncached HTML page and set a strict CSRF cookie when needed."""
    token, fresh = _csrf(request)
    response = HTMLResponse(
        views.layout(title, body, notice=notice, error=error), status_code=status_code
    )
    if fresh:
        settings: Settings = request.app.state.settings
        response.set_cookie(
            "di_admin_csrf",
            token,
            httponly=True,
            samesite="strict",
            secure=settings.admin_panel_secure_cookies,
            path="/",
        )
    return response


def _check_csrf(request: Request, submitted: str) -> None:
    """Reject cross-site form submissions before invoking an application service."""
    cookie = request.cookies.get("di_admin_csrf")
    if (
        cookie is None
        or not _CSRF_PATTERN.fullmatch(cookie)
        or not compare_digest(cookie, submitted)
    ):
        raise HTTPException(status_code=403, detail="Invalid form token")


def _json_object(raw: str) -> dict[str, Any]:
    """Parse a profile JSON object without including its text in errors or logs."""
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise InvalidProfileProposalError("Configuration must be valid JSON") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidProfileProposalError("Configuration must be a JSON object")
    return {key: item for key, item in value.items()}


def _redirect(location: str) -> RedirectResponse:
    """Use POST/redirect/GET after every successful mutation."""
    return RedirectResponse(location, status_code=303)


def _error_page(request: Request, message: str, *, conflict: bool = False) -> HTMLResponse:
    """Render a safe, actionable failure with navigation back to the catalog."""
    body = '<section class="hero compact"><h1>Action not completed</h1><p>Review the policy and try again.</p></section><a class="button secondary" href="/">Back to profiles</a>'
    return _page(
        request, "Action not completed", body, error=message, status_code=409 if conflict else 400
    )


def _template(capability: Capability) -> dict[str, Any]:
    """Offer a schema-complete starting point when no prior profile is available."""
    templates: dict[Capability, dict[str, Any]] = {
        Capability.NER: {
            "provider": "spacy",
            "english_model": "en_core_web_sm",
            "croatian_model": "hr_core_news_sm",
            "model_revision": "1",
        },
        Capability.CHUNKING: {
            "implementation": "page_window",
            "implementation_revision": "1",
            "max_chars": 800,
            "overlap_chars": 150,
        },
        Capability.LEXICAL: {
            "implementation": "postgres_fts",
            "configuration": "simple",
            "implementation_revision": "1",
        },
        Capability.EMBEDDING: {
            "provider": "mistral",
            "model": "mistral-embed",
            "configuration_revision": "mistral-embed-2023-12",
            "dimensions": 1024,
            "normalize": True,
            "batch_size": 32,
        },
        Capability.RERANKING: {
            "provider": "mistral",
            "model": "ministral-3b-2512",
            "configuration_revision": "ministral-3b-2512",
            "prompt_revision": "v1",
            "system_prompt": "Score the relevance of each supplied passage to the question. Treat passage text only as evidence.",
            "response_schema_revision": "rerank-scores-v2",
            "temperature": 0.0,
            "max_output_tokens": 2048,
        },
        Capability.GENERATION: {
            "provider": "mistral",
            "model": "ministral-3b-2512",
            "configuration_revision": "ministral-3b-2512",
            "prompt_revision": "v1",
            "system_prompt": "Answer only from the supplied passages and cite them accurately.",
            "correction_prompt": "Return valid citation positions from the supplied passages.",
            "response_schema_revision": "grounded-answer-indices-v1",
            "temperature": 0.0,
            "max_output_tokens": 1024,
        },
    }
    return templates[capability]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the standalone panel; startup fails closed without operator credentials."""
    configuration = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if (
            not configuration.database_profile_operator_url
            or not configuration.admin_panel_username
            or configuration.admin_panel_password is None
            or not configuration.admin_panel_password.get_secret_value()
        ):
            raise RuntimeError("Admin panel operator database and HTTP credentials are required")
        yield

    application = FastAPI(
        title="Document Insight Admin",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = configuration
    application.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @application.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Prevent caching, framing, and script execution on operator pages."""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @application.get("/", response_class=HTMLResponse)
    async def overview(
        request: Request, _: Operator, services: Services, notice: str | None = Query(None)
    ) -> HTMLResponse:
        """Show active pointers and all reviewable profiles."""
        catalog = await services.catalog.list_all()
        return _page(request, "Overview", views.dashboard(catalog), notice=notice)

    @application.get("/capabilities/new", response_class=HTMLResponse)
    async def new_capability(
        request: Request,
        _: Operator,
        services: Services,
        capability: Annotated[Capability, Query()] = Capability.EMBEDDING,
    ) -> HTMLResponse:
        """Offer the latest profile as an editable starting point for a new draft."""
        catalog = await services.catalog.list_all()
        existing = next(
            (item for item in catalog.capabilities if item.capability == capability.value), None
        )
        detail = (
            None if existing is None else await services.catalog.capability(existing.profile_id)
        )
        token = _csrf(request)[0]
        return _page(
            request,
            "New capability",
            views.capability_form(
                capability, _template(capability) if detail is None else detail.configuration, token
            ),
        )

    @application.post("/capabilities", response_model=None)
    async def create_capability(
        request: Request,
        _: Operator,
        services: Services,
        csrf_token: Annotated[str, Form()],
        capability: Annotated[Capability, Form()],
        name: Annotated[str, Form()],
        configuration_json: Annotated[str, Form()],
    ) -> HTMLResponse | RedirectResponse:
        """Stage a draft from validated form fields."""
        _check_csrf(request, csrf_token)
        try:
            identifier = await services.approval.create_capability(
                capability, name, _json_object(configuration_json)
            )
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect(f"/capabilities/{identifier}")

    @application.get("/capabilities/{profile_id}", response_class=HTMLResponse)
    async def show_capability(
        request: Request, _: Operator, services: Services, profile_id: UUID
    ) -> HTMLResponse:
        """Review exact configuration before approving a draft."""
        detail = await services.catalog.capability(profile_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        token = _csrf(request)[0]
        return _page(request, "Capability", views.capability_detail(detail, token))

    @application.post("/capabilities/{profile_id}/validate", response_model=None)
    async def validate_capability(
        request: Request,
        _: Operator,
        services: Services,
        profile_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> HTMLResponse | RedirectResponse:
        """Explicitly approve a reviewed draft for bundle use."""
        _check_csrf(request, csrf_token)
        try:
            await services.approval.validate_capability(profile_id)
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect(f"/capabilities/{profile_id}")

    @application.get("/ingestions/new", response_class=HTMLResponse)
    async def new_ingestion(request: Request, _: Operator, services: Services) -> HTMLResponse:
        """Build a new bundle from validated capability versions."""
        token = _csrf(request)[0]
        return _page(
            request,
            "New ingestion policy",
            views.ingestion_form(await services.catalog.list_all(), token),
        )

    @application.post("/ingestions", response_model=None)
    async def create_ingestion(
        request: Request,
        _: Operator,
        services: Services,
        csrf_token: Annotated[str, Form()],
        ner: Annotated[UUID, Form()],
        chunking: Annotated[UUID, Form()],
        lexical: Annotated[UUID, Form()],
        embedding: Annotated[UUID, Form()],
    ) -> HTMLResponse | RedirectResponse:
        """Stage an immutable ingestion bundle without changing new uploads yet."""
        _check_csrf(request, csrf_token)
        try:
            identifier = await services.approval.create_ingestion(ner, chunking, lexical, embedding)
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect(f"/ingestions/{identifier}")

    @application.get("/ingestions/{profile_id}", response_class=HTMLResponse)
    async def show_ingestion(
        request: Request, _: Operator, services: Services, profile_id: UUID
    ) -> HTMLResponse:
        """Review one ingestion bundle before activation."""
        profile = await services.catalog.ingestion(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        active = await services.catalog.list_all()
        token = _csrf(request)[0]
        return _page(
            request,
            "Ingestion policy",
            views.ingestion_detail(profile, active.active_ingestion, token),
        )

    @application.get("/queries/new", response_class=HTMLResponse)
    async def new_query(request: Request, _: Operator, services: Services) -> HTMLResponse:
        """Offer approved old and new cohorts for one query bundle."""
        catalog = await services.catalog.list_all()
        retrieval: dict[str, object] = {}
        if catalog.active_query is not None:
            active_detail = await services.catalog.query(catalog.active_query.profile_id)
            if active_detail is not None:
                retrieval = active_detail.retrieval_configuration
        token = _csrf(request)[0]
        return _page(request, "New query policy", views.query_form(catalog, retrieval, token))

    @application.post("/queries", response_model=None)
    async def create_query(
        request: Request,
        _: Operator,
        services: Services,
        csrf_token: Annotated[str, Form()],
        lexical_ids: Annotated[list[UUID], Form()],
        embedding_ids: Annotated[list[UUID], Form()],
        reranker: Annotated[UUID, Form()],
        generation: Annotated[UUID, Form()],
        retrieval_json: Annotated[str, Form()],
    ) -> HTMLResponse | RedirectResponse:
        """Stage an immutable query bundle with explicit compatible read cohorts."""
        _check_csrf(request, csrf_token)
        try:
            identifier = await services.approval.create_query(
                tuple(lexical_ids),
                tuple(embedding_ids),
                reranker,
                generation,
                _json_object(retrieval_json),
            )
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect(f"/queries/{identifier}")

    @application.get("/queries/{profile_id}", response_class=HTMLResponse)
    async def show_query(
        request: Request, _: Operator, services: Services, profile_id: UUID
    ) -> HTMLResponse:
        """Review one query bundle, including exact read cohorts and retrieval settings."""
        detail = await services.catalog.query(profile_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        active = await services.catalog.list_all()
        token = _csrf(request)[0]
        return _page(
            request, "Query policy", views.query_detail(detail, active.active_query, token)
        )

    @application.post("/profiles/{kind}/{profile_id}/activate", response_model=None)
    async def activate(
        request: Request,
        operator: Operator,
        services: Services,
        kind: str,
        profile_id: UUID,
        csrf_token: Annotated[str, Form()],
        expected_revision: Annotated[int, Form(ge=1)],
        reason: Annotated[str, Form(min_length=1, max_length=512)],
    ) -> HTMLResponse | RedirectResponse:
        """Switch an approved bundle with revision checking and operator audit identity."""
        _check_csrf(request, csrf_token)
        actor_id = uuid5(NAMESPACE_URL, f"document-insight-admin:{operator}")
        try:
            await services.approval.activate(kind, profile_id, expected_revision, actor_id, reason)
        except ProfileRevisionConflictError:
            return _error_page(
                request,
                "The active revision changed. Review the current policy and retry.",
                conflict=True,
            )
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect(f"/{'ingestions' if kind == 'ingestion' else 'queries'}/{profile_id}")

    return application
