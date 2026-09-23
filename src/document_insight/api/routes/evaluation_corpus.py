"""Browser entrypoint for tenant-authenticated evaluation document uploads."""

from html import escape
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from document_insight.api.dependencies import get_current_user
from document_insight.api.errors import raise_api_error
from document_insight.api.schemas.common import ApiModel
from document_insight.application.auth.models import AuthorizationContext, UserRole

router = APIRouter(prefix="/evaluation-corpus", tags=["evaluation corpus"])
CurrentUser = Annotated[AuthorizationContext, Depends(get_current_user)]
_PAGE = Path(__file__).resolve().parents[1] / "static" / "evaluation_corpus" / "index.html"


class EvaluationCorpusIdentityDTO(ApiModel):
    """Current tenant identity and permitted upload/activation actions."""

    tenant_id: UUID
    user_id: UUID
    role: UserRole
    can_activate: bool


@router.get("/upload", include_in_schema=False, response_class=HTMLResponse)
async def upload_page(
    tenant_id: UUID | None = Query(None),  # noqa: B008
    tenant_name: str | None = Query(None, max_length=120),  # noqa: B008
) -> HTMLResponse:
    """Show the selected tenant before login; file bytes go only to POST /ingest."""
    context = ""
    if tenant_id is not None:
        label = escape(tenant_name.strip() if tenant_name and tenant_name.strip() else "Tenant")
        context = (
            '<div class="selected-tenant" aria-label="Selected tenant">'
            f"<span>Selected tenant from Admin Panel</span><strong>{label}</strong>"
            f"<code>{tenant_id}</code></div>"
        )
    page = _PAGE.read_text(encoding="utf-8").replace("<!-- selected tenant context -->", context)
    return HTMLResponse(
        content=page,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ),
        },
    )


@router.get("/identity", response_model=EvaluationCorpusIdentityDTO)
async def evaluation_identity(
    current_user: CurrentUser,
) -> EvaluationCorpusIdentityDTO:
    """Permit only editors and tenant admins to upload through this page."""
    if current_user.role is UserRole.VIEWER:
        raise_api_error(403, "evaluation_identity_required", "Use an editor or tenant admin.")
    return EvaluationCorpusIdentityDTO(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
        can_activate=current_user.role is UserRole.TENANT_ADMIN,
    )
