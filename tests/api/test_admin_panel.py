"""Browser security and review flow for the private configuration panel."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi.testclient import TestClient
from pydantic import SecretStr

from document_insight.admin_panel.app import PanelServices, _services, create_app
from document_insight.application.configuration.catalog import CapabilityDetail, ProfileCatalog
from document_insight.config import Settings
from document_insight.infrastructure.active_profile.protocol import ActiveProfile
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile


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
    fake = SimpleNamespace(
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
            query=AsyncMock(return_value=None),
        ),
    )
    app.dependency_overrides[_services] = lambda: PanelServices(fake.approval, fake.catalog)
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
