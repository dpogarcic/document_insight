"""Browser security and review flow for the private configuration panel."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi.testclient import TestClient
from pydantic import SecretStr

from document_insight.admin_panel import views
from document_insight.admin_panel.app import PanelServices, _services, create_app
from document_insight.admin_panel.evaluation_routes import (
    _evaluation_services,
    _evaluation_templates,
    _evaluation_tenants,
)
from document_insight.application.configuration.catalog import CapabilityDetail, ProfileCatalog
from document_insight.config import Settings
from document_insight.infrastructure.active_profile.protocol import ActiveProfile
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.document.protocol import EvaluationDocumentOption
from document_insight.infrastructure.evaluation_case_result.protocol import (
    CaseResultStatus,
    EvaluationCaseResult,
)
from document_insight.infrastructure.evaluation_suite.protocol import EvaluationSuiteRevision
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
)
from document_insight.infrastructure.query_profile.protocol import ResolvedQueryProfile
from document_insight.infrastructure.tenant.protocol import TenantSummary


def _client(
    *, catalog: ProfileCatalog | None = None, detail: CapabilityDetail | None = None
) -> tuple[TestClient, SimpleNamespace]:
    """Use fake application boundaries so UI tests need no database or Docker."""
    settings = Settings(
        jwt_secret_key=SecretStr("test-only-secret"),
        database_profile_operator_url="sqlite+aiosqlite:///:memory:",
        admin_panel_username="operator",
        admin_panel_password=SecretStr("test-password"),
    )
    app = create_app(settings)
    tenant_id = uuid4()
    fake = SimpleNamespace(
        tenant_id=tenant_id,
        approval=SimpleNamespace(
            create_capability=AsyncMock(return_value=uuid4()),
            validate_capability=AsyncMock(),
            create_ingestion=AsyncMock(return_value=uuid4()),
            create_query=AsyncMock(return_value=uuid4()),
            activate=AsyncMock(return_value=2),
        ),
        catalog=SimpleNamespace(
            list_all=AsyncMock(return_value=catalog or ProfileCatalog((), (), (), None, None)),
            capability=AsyncMock(return_value=detail),
            ingestion=AsyncMock(return_value=None),
            evaluation_ingestion=AsyncMock(return_value=None),
            query=AsyncMock(return_value=None),
        ),
    )
    app.dependency_overrides[_services] = lambda: PanelServices(fake.approval, fake.catalog)
    app.dependency_overrides[_evaluation_templates] = lambda: ()
    app.dependency_overrides[_evaluation_tenants] = lambda: (
        TenantSummary(tenant_id, "Example tenant"),
    )
    client = TestClient(app, follow_redirects=False)
    client.auth = ("operator", "test-password")
    return client, fake


def _token(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


def test_panel_requires_operator_login_and_sets_browser_security_headers() -> None:
    client, fake = _client()
    with client:
        unauthenticated = client.get("/", auth=None)
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["www-authenticate"].startswith("Basic")
        assert fake.catalog.list_all.await_count == 0

        response = client.get("/")
        assert response.status_code == 200
        assert "Configuration profiles" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert "script-src" not in response.headers["content-security-policy"]
        assert "connect-src" not in response.headers["content-security-policy"]


def test_evaluation_pages_are_operator_only_and_show_suite_creation() -> None:
    """The evaluation UI is registered but remains protected by operator login."""
    client, _ = _client()
    with client:
        page = client.get("/")
        assert "/evaluations/suites" in page.text
        assert client.get("/evaluations/suites/new", auth=None).status_code == 401
        form = client.get("/evaluations/suites/new")
        assert form.status_code == 200
        assert "script-src 'self'" in form.headers["content-security-policy"]
        assert "connect-src 'self'" in form.headers["content-security-policy"]
        assert "relevance_complete" in form.text
        assert "data-case-template" in form.text
        assert "data-add-case" in form.text
        assert "data-corpus-choice" in form.text
        assert "data-add-corpus" not in form.text
        assert "data-json-preview" in form.text
        assert '<textarea name="test_cases_json"' not in form.text
        assert 'class="form-actions"' in form.text
        assert "Example tenant" in form.text
        assert 'name="tenant_id"' in form.text


def test_all_tenants_filter_accepts_empty_form_value() -> None:
    client, fake = _client()
    evaluations = SimpleNamespace(list_suites=AsyncMock(return_value=()))
    client.app.dependency_overrides[_evaluation_services] = lambda: evaluations
    with client:
        all_tenants = client.get("/evaluations/suites?tenant_id=")
        assert all_tenants.status_code == 200
        assert "All tenants" in all_tenants.text
        evaluations.list_suites.assert_awaited_with("", None)

        one_tenant = client.get(f"/evaluations/suites?tenant_id={fake.tenant_id}")
        assert one_tenant.status_code == 200
        evaluations.list_suites.assert_awaited_with("", fake.tenant_id)

        invalid = client.get("/evaluations/suites?tenant_id=not-a-uuid")
        assert invalid.status_code == 422


def test_suite_creation_uses_selected_existing_tenant() -> None:
    client, fake = _client()
    revision_id = uuid4()
    evaluations = SimpleNamespace(create_suite_revision=AsyncMock(return_value=revision_id))
    client.app.dependency_overrides[_evaluation_services] = lambda: evaluations
    with client:
        page = client.get("/evaluations/suites/new")
        payload = {
            "csrf_token": _token(page.text),
            "suite_name": "quality",
            "tenant_id": str(fake.tenant_id),
            "test_cases_json": "[]",
            "corpus_version_ids_json": f'["{uuid4()}"]',
        }
        response = client.post("/evaluations/suites", data=payload)
        assert response.status_code == 303
        assert evaluations.create_suite_revision.await_args.args[3] == fake.tenant_id

        payload["tenant_id"] = str(uuid4())
        rejected = client.post("/evaluations/suites", data=payload)
        assert rejected.status_code == 400
        assert evaluations.create_suite_revision.await_count == 1


def _suite_revision(tenant_id, number: int, question: str = "What is <x>?"):  # type: ignore[no-untyped-def]
    revision_id, version_id = uuid4(), uuid4()
    case = EvaluationTestCase(
        uuid4(),
        revision_id,
        question,
        None,
        uuid4(),
        Answerability.ANSWERABLE,
        {"fact": "value"},
        "Check the source",
        {"scenario": "baseline"},
        (f"{version_id}@1:0:10",),
        0,
        True,
    )
    return EvaluationSuiteRevision(
        revision_id,
        "quality",
        number,
        uuid4(),
        "2026-09-23T00:00:00Z",
        (case,),
        tenant_id,
        (version_id,),
        "a" * 64,
    )


def test_suite_edit_opens_prefilled_form_with_fixed_name_and_tenant() -> None:
    client, fake = _client()
    suite = _suite_revision(fake.tenant_id, 2)
    evaluations = SimpleNamespace(get_suite_revision=AsyncMock(return_value=suite))
    client.app.dependency_overrides[_evaluation_services] = lambda: evaluations
    with client:
        assert (
            client.get(f"/evaluations/suites/{suite.revision_id}/edit", auth=None).status_code
            == 401
        )
        page = client.get(f"/evaluations/suites/{suite.revision_id}/edit")
        assert page.status_code == 200
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert "connect-src 'self'" in page.headers["content-security-policy"]
        assert f'name="base_revision_id" value="{suite.revision_id}"' in page.text
        assert 'name="suite_name" maxlength="200" required readonly value="quality"' in page.text
        assert page.text.count("<option value=") >= 1
        assert "Choose a tenant</option>" not in page.text
        assert "Saving creates version 3" in page.text
        assert "What is &lt;x&gt;?" in page.text  # prefill JSON is escaped into the attribute
        prefill = views.suite_prefill(suite)
        assert prefill["corpus_version_ids"] == [str(suite.corpus_version_ids[0])]
        assert set(prefill["test_cases"][0]) == {
            "question",
            "authorized_identity_id",
            "answerability",
            "relevance_complete",
            "relevant_passage_ids",
            "filter_text",
            "expected_facts",
            "review_rubric",
            "tags",
        }
        # Other suite pages keep the stricter policy.
        assert "script-src" not in client.get("/").headers["content-security-policy"]


def test_suite_edit_saves_next_revision_only_from_the_latest_version() -> None:
    client, fake = _client()
    older = _suite_revision(fake.tenant_id, 1)
    latest = _suite_revision(fake.tenant_id, 2)
    new_id = uuid4()
    revisions = {older.revision_id: older, latest.revision_id: latest}
    evaluations = SimpleNamespace(
        get_suite_revision=AsyncMock(side_effect=lambda revision_id: revisions.get(revision_id)),
        list_suites=AsyncMock(return_value=(latest, older)),
        create_suite_revision=AsyncMock(return_value=new_id),
    )
    client.app.dependency_overrides[_evaluation_services] = lambda: evaluations
    with client:
        page = client.get(f"/evaluations/suites/{latest.revision_id}/edit")
        payload = {
            "csrf_token": _token(page.text),
            "suite_name": "quality",
            "tenant_id": str(fake.tenant_id),
            "test_cases_json": "[]",
            "corpus_version_ids_json": f'["{latest.corpus_version_ids[0]}"]',
            "base_revision_id": str(older.revision_id),
        }
        stale = client.post("/evaluations/suites", data=payload)
        assert stale.status_code == 400
        assert "saved as version 2" in stale.text
        assert evaluations.create_suite_revision.await_count == 0

        payload["base_revision_id"] = str(latest.revision_id)
        payload["suite_name"] = "renamed"
        renamed = client.post("/evaluations/suites", data=payload)
        assert renamed.status_code == 400
        assert evaluations.create_suite_revision.await_count == 0

        payload["suite_name"] = "quality"
        saved = client.post("/evaluations/suites", data=payload)
        assert saved.status_code == 303
        assert saved.headers["location"] == f"/evaluations/suites/{new_id}"
        assert evaluations.create_suite_revision.await_args.args[0] == "quality"


def test_suite_list_shows_latest_version_per_suite_and_detail_links_history() -> None:
    older = _suite_revision(uuid4(), 1)
    latest = _suite_revision(older.evaluation_tenant_id, 2)
    listing = views.list_suites((older, latest), "token")
    assert listing.count("<tr><td><a") == 1
    assert f"/evaluations/suites/{latest.revision_id}/edit" in listing
    assert "2 versions" in listing

    catalog = ProfileCatalog((), (), (), None, None)
    current = views.suite_detail(latest, "token", catalog, revisions=(latest, older))
    assert f"/evaluations/suites/{latest.revision_id}/edit" in current
    assert f'/evaluations/suites/{older.revision_id}"' in current
    past = views.suite_detail(older, "token", catalog, revisions=(latest, older))
    assert "/edit" not in past
    assert "The latest is version 2" in past


def test_test_corpus_upload_link_names_selected_tenant() -> None:
    client, fake = _client()
    client.app.state.settings.evaluation_tenant_id = fake.tenant_id
    with client:
        response = client.get("/evaluations/corpus")
    assert response.status_code == 200
    assert f"tenant_id={fake.tenant_id}" in response.text
    assert "tenant_name=Example+tenant" in response.text


def test_corpus_picker_lists_activated_versions_for_selected_tenant(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, fake = _client()
    document_id, version_id = uuid4(), uuid4()
    repository = SimpleNamespace(
        list_active_for_operator=AsyncMock(
            return_value=(EvaluationDocumentOption(document_id, "Test document", version_id),)
        )
    )
    monkeypatch.setattr(
        "document_insight.admin_panel.evaluation_routes.SqlAlchemyDocumentRepository",
        lambda session: repository,
    )
    with client:
        path = f"/evaluations/corpus/versions?tenant_id={fake.tenant_id}"
        assert client.get(path, auth=None).status_code == 401
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == [
            {
                "document_id": str(document_id),
                "title": "Test document",
                "version_id": str(version_id),
            }
        ]
        repository.list_active_for_operator.assert_awaited_once_with(fake.tenant_id)
        assert client.get(f"/evaluations/corpus/versions?tenant_id={uuid4()}").status_code == 404


def test_run_review_shows_approved_case_labels_with_escaped_content() -> None:
    run_id, suite_id, case_id = uuid4(), uuid4(), uuid4()
    case = EvaluationTestCase(
        case_id,
        suite_id,
        "What is the <target>?",
        None,
        uuid4(),
        Answerability.ANSWERABLE,
        {"fact": "approved"},
        "Check <source>",
        {},
        (),
        0,
        True,
    )
    suite = EvaluationSuiteRevision(
        suite_id,
        "quality",
        1,
        uuid4(),
        "2026-09-23T00:00:00Z",
        (case,),
    )
    result = EvaluationCaseResult(
        uuid4(),
        run_id,
        case_id,
        CaseResultStatus.COMPLETED,
        (),
        {},
        (),
        (),
        (),
        (),
        "candidate answer",
        "answered",
        (),
        {},
        "2026-09-23T00:00:00Z",
        "2026-09-23T00:00:01Z",
    )
    record = SimpleNamespace(
        run_id=run_id,
        suite_revision_id=suite_id,
        suite_name="quality",
        revision_number=1,
        status="completed",
        case_count=1,
        completed_case_count=1,
        started_at=None,
        completed_at=None,
        baseline_profile_ids=(),
        candidate_profile_ids=(),
        k_values=(),
        config_fingerprints={},
        error_message=None,
    )
    run = SimpleNamespace(per_case_results=(result,), aggregate_measurements=())
    page = views.run_detail(record, "token", run, None, suite)
    assert "What is the &lt;target&gt;?" in page
    assert "Check &lt;source&gt;" in page
    assert "candidate answer" in page


def test_operator_launches_query_comparison_from_suite_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    baseline_id, candidate_id = uuid4(), uuid4()
    suite_id, source_id, run_id = uuid4(), uuid4(), uuid4()
    catalog = ProfileCatalog(
        (),
        (),
        (ResolvedQueryProfile(candidate_id, (uuid4(),), (uuid4(),), uuid4(), uuid4(), uuid4()),),
        None,
        ActiveProfile(baseline_id, 1),
    )
    client, _ = _client(catalog=catalog)
    suite = EvaluationSuiteRevision(
        suite_id,
        "quality",
        1,
        uuid4(),
        "2026-09-23T00:00:00Z",
        (),
        uuid4(),
        (source_id,),
        "a" * 64,
    )
    evaluations = SimpleNamespace(
        get_suite_revision=AsyncMock(return_value=suite),
        launch_run=AsyncMock(return_value=run_id),
        mark_enqueued=AsyncMock(),
        list_suites=AsyncMock(return_value=(suite,)),
    )
    client.app.dependency_overrides[_evaluation_services] = lambda: evaluations
    queue = SimpleNamespace(enqueue=AsyncMock())
    monkeypatch.setattr(
        "document_insight.admin_panel.evaluation_routes.RqEvaluationQueue",
        lambda *_: queue,
    )
    with client:
        page = client.get(f"/evaluations/suites/{suite_id}")
        assert page.status_code == 200
        response = client.post(
            "/evaluations/runs",
            data={
                "csrf_token": _token(page.text),
                "suite_revision_id": str(suite_id),
                "candidate_profile_id": str(candidate_id),
                "k_values_json": "[1,5]",
                "evaluation_mode": "query",
            },
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/evaluations/runs/{run_id}"
        command = evaluations.launch_run.await_args.args[0]
        assert command.corpus_manifest["baseline"]["version_ids"] == [str(source_id)]
        queue.enqueue.assert_awaited_once_with(run_id)


def test_capability_form_requires_matching_csrf_cookie_and_stages_draft() -> None:
    client, fake = _client()
    with client:
        form = client.get("/capabilities/new?capability=embedding")
        assert form.status_code == 200
        token = _token(form.text)
        assert client.cookies.get("di_admin_csrf") == token
        assert "HttpOnly" in form.headers["set-cookie"]

        payload = {
            "csrf_token": "invalid",
            "capability": "embedding",
            "name": "new-model",
            "configuration_json": '{"provider":"mistral"}',
        }
        denied = client.post("/capabilities", data=payload)
        assert denied.status_code == 403
        fake.approval.create_capability.assert_not_awaited()

        payload["csrf_token"] = token
        created = client.post("/capabilities", data=payload)
        assert created.status_code == 303
        assert created.headers["location"].startswith("/capabilities/")
        fake.approval.create_capability.assert_awaited_once()


def test_activation_uses_reviewed_revision_and_authenticated_operator_identity() -> None:
    old_id, candidate_id = uuid4(), uuid4()
    catalog = ProfileCatalog((), (), (), ActiveProfile(old_id, 4), ActiveProfile(old_id, 7))
    client, fake = _client(catalog=catalog)
    with client:
        page = client.get("/")
        token = client.cookies.get("di_admin_csrf")
        assert token is not None and page.status_code == 200
        activated = client.post(
            f"/profiles/query/{candidate_id}/activate",
            data={"csrf_token": token, "expected_revision": "7", "reason": "approved rollout"},
        )
        assert activated.status_code == 303
        fake.approval.activate.assert_awaited_once_with(
            "query",
            candidate_id,
            7,
            uuid5(NAMESPACE_URL, "document-insight-admin:operator"),
            "approved rollout",
        )


def test_profile_content_is_escaped_before_rendering() -> None:
    profile_id, snapshot_id = uuid4(), uuid4()
    profile = CapabilityProfile(
        profile_id, "generation", snapshot_id, "draft", "<script>alert(1)</script>"
    )
    client, _ = _client(
        detail=CapabilityDetail(profile, {"system_prompt": "</pre><script>x</script>"})
    )
    with client:
        page = client.get(f"/capabilities/{profile_id}")
        assert page.status_code == 200
        assert "<script>" not in page.text
        assert "&lt;script&gt;" in page.text


def test_bundle_forms_and_capability_approval_call_application_services() -> None:
    """Each visible action reaches the existing approval layer with typed profile IDs."""
    client, fake = _client()
    ner, chunking, lexical, embedding, reranker, generation = (uuid4() for _ in range(6))
    with client:
        client.get("/")
        token = client.cookies.get("di_admin_csrf")
        assert token is not None
        capability_id = uuid4()
        validated = client.post(
            f"/capabilities/{capability_id}/validate", data={"csrf_token": token}
        )
        assert validated.status_code == 303
        fake.approval.validate_capability.assert_awaited_once_with(capability_id)

        ingestion = client.post(
            "/ingestions",
            data={
                "csrf_token": token,
                "ner": str(ner),
                "chunking": str(chunking),
                "lexical": str(lexical),
                "embedding": str(embedding),
            },
        )
        assert ingestion.status_code == 303
        fake.approval.create_ingestion.assert_awaited_once_with(ner, chunking, lexical, embedding)

        retrieval = '{"lexical_candidate_limit":10}'
        query = client.post(
            "/queries",
            data={
                "csrf_token": token,
                "lexical_ids": [str(lexical)],
                "embedding_ids": [str(embedding)],
                "reranker": str(reranker),
                "generation": str(generation),
                "retrieval_json": retrieval,
            },
        )
        assert query.status_code == 303
        fake.approval.create_query.assert_awaited_once_with(
            (lexical,),
            (embedding,),
            reranker,
            generation,
            {"lexical_candidate_limit": 10},
        )
