"""Admin panel routes for evaluation suite and run management.

This module registers evaluation routes on the admin panel application.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.admin_panel.app import Operator, Services
from document_insight.application.configuration.exceptions import (
    InvalidProfileProposalError,
    ProfileRevisionConflictError,
)
from document_insight.application.evaluation.commands import (
    LaunchEvaluationRunCommand,
)
from document_insight.application.evaluation.exceptions import EvaluationError
from document_insight.application.evaluation.models import CorpusVariant, EvaluationCorpusManifest
from document_insight.application.evaluation.service import EvaluationService
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.document.repository import SqlAlchemyDocumentRepository
from document_insight.infrastructure.evaluation_aggregate.repository import (
    SqlAlchemyEvaluationAggregateRepository,
)
from document_insight.infrastructure.evaluation_case_result.repository import (
    SqlAlchemyEvaluationCaseResultRepository,
)
from document_insight.infrastructure.evaluation_case_template.protocol import EvaluationCaseTemplate
from document_insight.infrastructure.evaluation_case_template.repository import (
    SqlAlchemyEvaluationCaseTemplateRepository,
)
from document_insight.infrastructure.evaluation_gate_review.repository import (
    SqlAlchemyEvaluationGateReviewRepository,
)
from document_insight.infrastructure.evaluation_run.repository import (
    SqlAlchemyEvaluationRunRepository,
)
from document_insight.infrastructure.evaluation_suite.repository import (
    SqlAlchemyEvaluationSuiteRepository,
)
from document_insight.infrastructure.evaluation_test_case.repository import (
    SqlAlchemyEvaluationTestCaseRepository,
)
from document_insight.infrastructure.ingestion_profile.repository import (
    SqlAlchemyIngestionProfileRepository,
)
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)
from document_insight.infrastructure.queue.evaluation import RqEvaluationQueue
from document_insight.infrastructure.tenant.protocol import TenantSummary
from document_insight.infrastructure.tenant.repository import SqlAlchemyTenantRepository

# ---------------------------------------------------------------------------
# Dependency factories – module-level so FastAPI can resolve string annotations
# via typing.get_type_hints() looking at module globals
# ---------------------------------------------------------------------------


async def _evaluation_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session for evaluation operations."""
    from document_insight.infrastructure.database.session import get_session_factory

    async with get_session_factory("profile_operator")() as session:
        yield session


EvaluationSessionType = Annotated[AsyncSession, Depends(_evaluation_session)]


async def _evaluation_templates(
    session: EvaluationSessionType,
) -> tuple[EvaluationCaseTemplate, ...]:
    """Read the migration-owned scenario catalog for suite drafting."""
    return await SqlAlchemyEvaluationCaseTemplateRepository(session).list_all()


EvaluationTemplatesType = Annotated[
    tuple[EvaluationCaseTemplate, ...], Depends(_evaluation_templates)
]


async def _evaluation_tenants(session: EvaluationSessionType) -> tuple[TenantSummary, ...]:
    """List operator-visible tenant metadata without document or identity reads."""
    tenants = await SqlAlchemyTenantRepository(session).list_for_operator()
    # The evaluation service opens its own explicit transaction on this session.
    await session.rollback()
    return tenants


EvaluationTenantsType = Annotated[tuple[TenantSummary, ...], Depends(_evaluation_tenants)]


class EvaluationDocumentOptionDTO(BaseModel):
    """Metadata-only activated version for the suite document picker."""

    document_id: UUID
    title: str
    version_id: UUID


def _optional_tenant_id(raw: str | None) -> UUID | None:
    """Treat the All tenants form value as an absent filter."""
    if raw is None or not raw.strip():
        return None
    try:
        return UUID(raw)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid tenant ID") from error


def _evaluation_services(
    request: Request,
    _: Operator,
    session: EvaluationSessionType,
) -> EvaluationService:
    """Compose evaluation services."""
    suite_repo = SqlAlchemyEvaluationSuiteRepository(session)
    run_repo = SqlAlchemyEvaluationRunRepository(session)
    transactions = SqlAlchemyTransactionManager(session)
    return EvaluationService(
        suite_repo,
        run_repo,
        transactions,
        SqlAlchemyEvaluationCaseResultRepository(session),
        SqlAlchemyEvaluationAggregateRepository(session),
        SqlAlchemyEvaluationGateReviewRepository(session),
        SqlAlchemyEvaluationTestCaseRepository(session),
        SqlAlchemyQueryProfileRepository(session),
        SqlAlchemyCapabilityProfileRepository(session),
        SqlAlchemyConfigurationSnapshotRepository(session),
        SqlAlchemyIngestionProfileRepository(session),
    )


EvaluationServicesType = Annotated[EvaluationService, Depends(_evaluation_services)]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def create_evaluation_routes(application: FastAPI) -> None:
    """Add evaluation management routes to the admin panel."""
    from document_insight.admin_panel import views
    from document_insight.admin_panel.app import (
        _check_csrf,
        _csrf,
        _error_page,
        _page,
        _redirect,
    )

    @application.get(
        "/evaluations/corpus/versions",
        response_model=list[EvaluationDocumentOptionDTO],
    )
    async def list_corpus_versions(
        _: Operator,
        session: EvaluationSessionType,
        tenants: EvaluationTenantsType,
        tenant_id: Annotated[UUID, Query()],
    ) -> list[EvaluationDocumentOptionDTO]:
        """List only current activated version metadata for a selected tenant."""
        if tenant_id not in {tenant.tenant_id for tenant in tenants}:
            raise HTTPException(status_code=404, detail="Tenant not found")
        documents = await SqlAlchemyDocumentRepository(session).list_active_for_operator(tenant_id)
        return [
            EvaluationDocumentOptionDTO(
                document_id=item.document_id,
                title=item.title,
                version_id=item.version_id,
            )
            for item in documents
        ]

    @application.get("/evaluations/suites", response_class=HTMLResponse, response_model=None)
    async def list_suites(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        templates: EvaluationTemplatesType,
        tenants: EvaluationTenantsType,
        suite_name: str | None = Query(None),
        tenant_id: str | None = Query(None),  # noqa: B008
    ) -> HTMLResponse:
        """List all evaluation suites."""
        selected_tenant_id = _optional_tenant_id(tenant_id)
        suites = await services.list_suites(suite_name or "", selected_tenant_id)
        token = _csrf(request)[0]
        body = views.list_suites(suites, token, templates, tenants, selected_tenant_id)
        return _page(request, "Evaluation Suites", body)

    @application.get("/evaluations/corpus", response_class=HTMLResponse, response_model=None)
    async def show_corpus_setup(
        request: Request, _: Operator, panel: Services, tenants: EvaluationTenantsType
    ) -> HTMLResponse:
        """Show the dedicated test tenant and its selected ingestion policy."""
        tenant_id = request.app.state.settings.evaluation_tenant_id
        catalog = await panel.catalog.list_all()
        selected = (
            None if tenant_id is None else await panel.catalog.evaluation_ingestion(tenant_id)
        )
        upload_url = (
            request.app.state.settings.api_public_base_url.rstrip("/") + "/evaluation-corpus/upload"
        )
        if tenant_id is not None:
            tenant_name = next(
                (tenant.name for tenant in tenants if tenant.tenant_id == tenant_id), "Tenant"
            )
            upload_url += "?" + urlencode({"tenant_id": str(tenant_id), "tenant_name": tenant_name})
        return _page(
            request,
            "Evaluation corpus",
            views.evaluation_corpus_setup(
                tenant_id,
                catalog,
                selected,
                _csrf(request)[0],
                upload_url,
            ),
        )

    @application.post("/evaluations/corpus/ingestion", response_model=None)
    async def select_corpus_ingestion(
        request: Request,
        operator: Operator,
        panel: Services,
        profile_id: Annotated[UUID, Form()],
        expected_revision: Annotated[int, Form(ge=0)],
        csrf_token: str = Form(),
        reason: str = Form(),
    ) -> HTMLResponse | RedirectResponse:
        """Select a candidate for new uploads in the test tenant only."""
        _check_csrf(request, csrf_token)
        tenant_id = request.app.state.settings.evaluation_tenant_id
        if tenant_id is None:
            return _error_page(request, "Configure an approved evaluation tenant first")
        try:
            await panel.approval.select_evaluation_ingestion(
                tenant_id,
                profile_id,
                expected_revision,
                uuid5(NAMESPACE_URL, f"document-insight-admin:{operator}"),
                reason,
            )
        except ProfileRevisionConflictError:
            return _error_page(
                request, "Evaluation selection changed; reload and retry", conflict=True
            )
        except InvalidProfileProposalError as error:
            return _error_page(request, str(error))
        return _redirect("/evaluations/corpus")

    @application.get("/evaluations/suites/new", response_class=HTMLResponse, response_model=None)
    async def new_suite(
        request: Request,
        _: Operator,
        templates: EvaluationTemplatesType,
        tenants: EvaluationTenantsType,
        tenant_id: str | None = Query(None),  # noqa: B008
    ) -> HTMLResponse:
        """Show form to create a new suite."""
        token = _csrf(request)[0]
        body = views.suite_form(
            token,
            templates,
            request.app.state.settings.api_public_base_url.rstrip("/")
            + "/evaluation-corpus/upload",
            tenants=tenants,
            selected_tenant_id=_optional_tenant_id(tenant_id),
        )
        return _page(request, "New Evaluation Suite", body)

    @application.post("/evaluations/suites", response_model=None)
    async def create_suite(
        request: Request,
        operator: Operator,
        services: EvaluationServicesType,
        tenants: EvaluationTenantsType,
        csrf_token: str = Form(),
        suite_name: str = Form(),
        tenant_id: UUID = Form(),  # noqa: B008
        test_cases_json: str = Form(),
        corpus_version_ids_json: str = Form(),
        base_revision_id: UUID | None = Form(None),  # noqa: B008
    ) -> HTMLResponse | RedirectResponse:
        """Create a suite, or save an edit as that suite's next revision."""
        _check_csrf(request, csrf_token)
        try:
            if base_revision_id is not None:
                base = await services.get_suite_revision(base_revision_id)
                if base is None:
                    raise EvaluationError("The suite you were editing no longer exists")
                if base.suite_name != suite_name.strip() or base.evaluation_tenant_id != tenant_id:
                    raise EvaluationError("A suite keeps its name and tenant when edited")
                latest = max(
                    (
                        item.revision_number
                        for item in await services.list_suites(base.suite_name, tenant_id)
                    ),
                    default=base.revision_number,
                )
                if latest != base.revision_number:
                    raise EvaluationError(
                        f"This suite was saved as version {latest} after you started editing "
                        f"version {base.revision_number}. Open the latest version and edit it instead."
                    )
            test_cases = json.loads(test_cases_json)
            if not isinstance(test_cases, list):
                raise EvaluationError("Test cases must be a JSON array")
            if tenant_id not in {tenant.tenant_id for tenant in tenants}:
                raise EvaluationError("Select an existing tenant")
            corpus_version_ids = tuple(UUID(value) for value in json.loads(corpus_version_ids_json))
            created_by = uuid5(NAMESPACE_URL, f"document-insight-admin:{operator}")
            revision_id = await services.create_suite_revision(
                suite_name,
                created_by,
                tuple(test_cases),
                tenant_id,
                corpus_version_ids,
            )
        except (EvaluationError, ValueError, TypeError) as e:
            return _error_page(request, str(e))
        return _redirect(f"/evaluations/suites/{revision_id}")

    @application.get(
        "/evaluations/suites/{revision_id}",
        response_class=HTMLResponse,
        response_model=None,
    )
    async def show_suite(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        panel: Services,
        revision_id: UUID,
    ) -> HTMLResponse:
        """Show a suite revision detail."""
        suite = await services.get_suite_revision(revision_id)
        if suite is None:
            raise HTTPException(status_code=404, detail="Suite not found")
        token = _csrf(request)[0]
        revisions = await services.list_suites(suite.suite_name, suite.evaluation_tenant_id)
        body = views.suite_detail(
            suite,
            token,
            await panel.catalog.list_all(),
            allow_ingestion=suite.evaluation_tenant_id
            == request.app.state.settings.evaluation_tenant_id,
            revisions=revisions,
        )
        return _page(request, "Suite Detail", body)

    @application.get(
        "/evaluations/suites/{revision_id}/edit",
        response_class=HTMLResponse,
        response_model=None,
    )
    async def edit_suite(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        templates: EvaluationTemplatesType,
        tenants: EvaluationTenantsType,
        revision_id: UUID,
    ) -> HTMLResponse:
        """Open the suite form pre-filled; saving creates the suite's next revision."""
        suite = await services.get_suite_revision(revision_id)
        if suite is None:
            raise HTTPException(status_code=404, detail="Suite not found")
        token = _csrf(request)[0]
        body = views.suite_form(
            token,
            templates,
            request.app.state.settings.api_public_base_url.rstrip("/")
            + "/evaluation-corpus/upload",
            tenants=tenants,
            selected_tenant_id=suite.evaluation_tenant_id,
            editing=suite,
        )
        return _page(request, f"Edit {suite.suite_name}", body)

    @application.get("/evaluations/runs", response_class=HTMLResponse, response_model=None)
    async def list_runs(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        status: str | None = Query(None),
        tenant_id: str | None = Query(None),  # noqa: B008
    ) -> HTMLResponse:
        """List evaluation runs."""
        selected_tenant_id = _optional_tenant_id(tenant_id)
        runs = await services.list_runs(status=status)
        records = []
        for r in runs:
            record = await services.get_run_record(r.run_id)
            if record is not None and (
                selected_tenant_id is None or record.tenant_id == selected_tenant_id
            ):
                records.append(record)
        token = _csrf(request)[0]
        body = views.list_runs(tuple(records), token)
        return _page(request, "Evaluation Runs", body)

    @application.post("/evaluations/runs", response_model=None)
    async def launch_run(
        request: Request,
        operator: Operator,
        services: EvaluationServicesType,
        panel: Services,
        suite_revision_id: Annotated[UUID, Form()],
        candidate_profile_id: Annotated[UUID, Form()],
        csrf_token: str = Form(),
        k_values_json: str = Form(),
        evaluation_mode: str = Form("query"),
        candidate_ingestion_profile_id: str = Form(""),
        candidate_version_mapping_json: str = Form("{}"),
    ) -> HTMLResponse | RedirectResponse:
        """Launch a new evaluation run."""
        _check_csrf(request, csrf_token)
        try:
            suite = await services.get_suite_revision(suite_revision_id)
            catalog = await panel.catalog.list_all()
            if suite is None or catalog.active_query is None:
                raise EvaluationError("Suite or active baseline query policy is unavailable")
            candidate = next(
                (
                    item
                    for item in catalog.selectable_queries
                    if item.query_profile_id == candidate_profile_id
                ),
                None,
            )
            if candidate is None:
                raise EvaluationError("Candidate query policy is unavailable")
            baseline_id = catalog.active_query.profile_id
            k_values = tuple(int(k) for k in json.loads(k_values_json))
            baseline_corpus = CorpusVariant(
                suite.corpus_version_ids,
                {value: value for value in suite.corpus_version_ids},
            )
            candidate_ingestion_id = None
            baseline_ingestion_id = None
            if evaluation_mode == "ingestion":
                if suite.evaluation_tenant_id != request.app.state.settings.evaluation_tenant_id:
                    raise EvaluationError(
                        "Ingestion comparisons currently require the isolated test tenant"
                    )
                if catalog.active_ingestion is None:
                    raise EvaluationError("No active baseline ingestion policy")
                baseline_ingestion_id = catalog.active_ingestion.profile_id
                candidate_ingestion_id = UUID(candidate_ingestion_profile_id)
                if candidate_ingestion_id not in {
                    item.ingestion_profile_id for item in catalog.ingestions
                }:
                    raise EvaluationError("Candidate ingestion policy is unavailable")
                raw_mapping = json.loads(candidate_version_mapping_json)
                if not isinstance(raw_mapping, dict):
                    raise EvaluationError("Candidate version mapping must be an object")
                mapping = {UUID(source): UUID(indexed) for source, indexed in raw_mapping.items()}
                candidate_corpus = CorpusVariant(
                    tuple(mapping.values()),
                    {indexed: source for source, indexed in mapping.items()},
                )
            else:
                candidate_corpus = baseline_corpus
            manifest = EvaluationCorpusManifest(
                suite.dataset_fingerprint,
                baseline_corpus,
                candidate_corpus,
                baseline_id,
                candidate_profile_id,
                baseline_ingestion_id,
                candidate_ingestion_id,
            )

            command = LaunchEvaluationRunCommand(
                suite_revision_id=suite_revision_id,
                baseline_profile_ids=(baseline_id,),
                candidate_profile_ids=(candidate_profile_id,),
                read_cohorts={
                    "lexical": candidate.lexical_profile_ids,
                    "embedding": candidate.embedding_profile_ids,
                },
                corpus_manifest=manifest.to_json(),
                evaluator_version="source-span-v1",
                k_values=k_values,
                requester_id=uuid5(NAMESPACE_URL, f"document-insight-admin:{operator}"),
                candidate_component_profiles=(
                    {"ingestion": candidate_ingestion_id}
                    if candidate_ingestion_id is not None
                    else None
                ),
                evaluation_mode=evaluation_mode,
            )
            run_id = await services.launch_run(command)
            await RqEvaluationQueue(
                request.app.state.settings.redis_url,
                request.app.state.settings.rq_evaluation_queue_name,
            ).enqueue(run_id)
            await services.mark_enqueued(run_id)
        except (EvaluationError, ValueError, TypeError, RuntimeError) as e:
            return _error_page(request, str(e))
        return _redirect(f"/evaluations/runs/{run_id}")

    @application.get("/evaluations/runs/{run_id}", response_class=HTMLResponse, response_model=None)
    async def show_run(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        run_id: UUID,
    ) -> HTMLResponse:
        """Show run detail and results."""
        record = await services.get_run_record(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found")
        token = _csrf(request)[0]
        run = await services.get_run(run_id)
        review = await services.get_gate_review(run_id)
        suite = await services.get_suite_revision(record.suite_revision_id)
        body = views.run_detail(record, token, run, review, suite)
        return _page(request, "Run Detail", body)

    @application.post("/evaluations/runs/{run_id}/review", response_model=None)
    async def review_run(
        request: Request,
        operator: Operator,
        services: EvaluationServicesType,
        run_id: UUID,
        csrf_token: str = Form(),
        decision: str = Form(),
        reason: str = Form(),
    ) -> HTMLResponse | RedirectResponse:
        """Record the operator's decision on one exact completed comparison."""
        _check_csrf(request, csrf_token)
        try:
            await services.create_gate_review(
                run_id,
                uuid5(NAMESPACE_URL, f"document-insight-admin:{operator}"),
                decision,
                reason,
                run_id,
            )
        except EvaluationError as error:
            return _error_page(request, str(error))
        return _redirect(f"/evaluations/runs/{run_id}")

    @application.post("/evaluations/runs/{run_id}/cases/{result_id}/quality", response_model=None)
    async def review_answer_quality(
        request: Request,
        _: Operator,
        services: EvaluationServicesType,
        run_id: UUID,
        result_id: UUID,
        csrf_token: str = Form(),
        score: float = Form(),
        note: str = Form(""),
    ) -> HTMLResponse | RedirectResponse:
        """Save a manual quality score before final gate approval."""
        _check_csrf(request, csrf_token)
        try:
            await services.review_answer_quality(run_id, result_id, score, note)
        except EvaluationError as error:
            return _error_page(request, str(error))
        return _redirect(f"/evaluations/runs/{run_id}")
