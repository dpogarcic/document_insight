"""Test-tenant policy selection applies only to future test uploads."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.ingestion.commands import IngestDocumentCommand
from document_insight.application.ingestion.service import IngestionService


class _Transactions:
    @asynccontextmanager
    async def begin(self):  # type: ignore[no-untyped-def]
        yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_test_tenant_upload_persists_selected_candidate_profile() -> None:
    tenant_id, department_id = uuid4(), uuid4()
    platform_id, candidate_id = uuid4(), uuid4()
    active = SimpleNamespace(
        get_ingestion_profile_id=AsyncMock(
            side_effect=lambda scope: (
                candidate_id if scope == f"evaluation:{tenant_id}" else platform_id
            )
        )
    )
    jobs = SimpleNamespace(create=AsyncMock(), mark_enqueued=AsyncMock())
    generations = SimpleNamespace(create=AsyncMock())
    service = IngestionService(
        documents=SimpleNamespace(create=AsyncMock()),
        departments=SimpleNamespace(),
        document_departments=SimpleNamespace(add_many=AsyncMock()),
        document_versions=SimpleNamespace(create=AsyncMock()),
        jobs=jobs,
        active_profiles=active,
        index_generations=generations,
        transactions=_Transactions(),
        object_storage=SimpleNamespace(put=AsyncMock(), delete=AsyncMock()),
        processing_queue=SimpleNamespace(enqueue_ingestion=AsyncMock()),
        max_upload_bytes=25 * 1024 * 1024,
        evaluation_tenant_id=tenant_id,
    )
    await service.ingest(
        IngestDocumentCommand(
            b"%PDF-1.4\n",
            "sample.pdf",
            "application/pdf",
            None,
            (),
            AuthorizationContext(uuid4(), tenant_id, (department_id,), UserRole.EDITOR),
            uuid4(),
        )
    )
    assert jobs.create.await_args.args[0].ingestion_profile_id == candidate_id
    assert generations.create.await_args.args[0].ingestion_profile_id == candidate_id
