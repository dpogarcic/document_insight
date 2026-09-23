"""The upload page uses an authenticated tenant identity and API permissions."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from document_insight.api.app import create_app
from document_insight.api.dependencies import get_current_user
from document_insight.application.auth.models import AuthorizationContext, UserRole


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_upload_page_is_served_by_public_api_without_embedded_credentials() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/evaluation-corpus/upload")
        script = await client.get("/evaluation-corpus/assets/upload.js")
    assert response.status_code == 200
    assert "Upload test documents" in response.text
    assert "POST /ingest" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert script.status_code == 200


@pytest.mark.anyio
async def test_upload_page_names_selected_tenant_before_sign_in_and_escapes_name() -> None:
    tenant_id = uuid4()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/evaluation-corpus/upload",
            params={"tenant_id": str(tenant_id), "tenant_name": "Acme <Research>"},
        )
    assert response.status_code == 200
    assert "Selected tenant from Admin Panel" in response.text
    assert "Acme &lt;Research&gt;" in response.text
    assert "Acme <Research>" not in response.text
    assert str(tenant_id) in response.text


@pytest.mark.anyio
async def test_identity_accepts_any_tenant_admin_but_rejects_viewer() -> None:
    tenant_id = uuid4()
    app = create_app()
    actor = AuthorizationContext(uuid4(), uuid4(), (uuid4(),), UserRole.TENANT_ADMIN)
    app.dependency_overrides[get_current_user] = lambda: actor
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        other_tenant = await client.get("/evaluation-corpus/identity")
        actor = AuthorizationContext(uuid4(), tenant_id, (uuid4(),), UserRole.VIEWER)
        viewer = await client.get("/evaluation-corpus/identity")
        actor = AuthorizationContext(uuid4(), tenant_id, (uuid4(),), UserRole.TENANT_ADMIN)
        admin = await client.get("/evaluation-corpus/identity")
    assert other_tenant.status_code == 200
    assert viewer.status_code == 403
    assert admin.status_code == 200
    assert admin.json()["can_activate"] is True
    assert admin.json()["tenant_id"] == str(tenant_id)
