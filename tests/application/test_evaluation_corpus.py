"""Evaluation corpus checks preserve tenant, activation, and byte-identical comparisons."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.evaluation.corpus import EvaluationCorpusValidator
from document_insight.application.evaluation.models import CorpusVariant, EvaluationCorpusManifest
from document_insight.application.ingestion.models import DocumentVersionStatus


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_validator_accepts_indexed_copies_only_when_hashes_match() -> None:
    tenant_id, source_id, copy_id = uuid4(), uuid4(), uuid4()
    baseline_id, candidate_id = uuid4(), uuid4()
    admin_id = uuid4()
    actors = SimpleNamespace(
        load=AsyncMock(
            return_value=AuthorizationContext(
                admin_id,
                tenant_id,
                (uuid4(),),
                UserRole.TENANT_ADMIN,
            )
        )
    )
    documents = SimpleNamespace(
        get_current_ready_version_id=AsyncMock(side_effect=lambda document_id, tenant: document_id)
    )
    versions = SimpleNamespace(
        get_document_id=AsyncMock(side_effect=lambda version_id, tenant: version_id),
        get_for_activation=AsyncMock(
            return_value=SimpleNamespace(status=DocumentVersionStatus.READY)
        ),
        get_content_sha256=AsyncMock(return_value="f" * 64),
    )
    generations = SimpleNamespace(has_ready_generation=AsyncMock(return_value=True))
    manifest = EvaluationCorpusManifest(
        "a" * 64,
        CorpusVariant((source_id,), {source_id: source_id}),
        CorpusVariant((copy_id,), {copy_id: source_id}),
        uuid4(),
        uuid4(),
        baseline_id,
        candidate_id,
    )
    suite = SimpleNamespace(
        test_cases=(SimpleNamespace(authorized_identity_id=admin_id),),
        evaluation_tenant_id=tenant_id,
    )
    validator = EvaluationCorpusValidator(
        actors,
        documents,
        versions,
        generations,
        tenant_id,
    )
    await validator.validate(suite, manifest)
    assert generations.has_ready_generation.await_count == 2

    versions.get_content_sha256.side_effect = lambda version_id, tenant: (
        "0" * 64 if version_id == copy_id else "f" * 64
    )
    with pytest.raises(ValueError, match="differs"):
        await validator.validate(suite, manifest)


@pytest.mark.anyio
async def test_validator_rejects_cross_tenant_identity_before_document_reads() -> None:
    selected_tenant, other_tenant, version_id = uuid4(), uuid4(), uuid4()
    user_id = uuid4()
    actors = SimpleNamespace(
        load=AsyncMock(
            return_value=AuthorizationContext(
                user_id, other_tenant, (uuid4(),), UserRole.TENANT_ADMIN
            )
        )
    )
    documents = SimpleNamespace(get_current_ready_version_id=AsyncMock())
    versions = SimpleNamespace(get_document_id=AsyncMock())
    corpus = CorpusVariant((version_id,), {version_id: version_id})
    manifest = EvaluationCorpusManifest("a" * 64, corpus, corpus, uuid4(), uuid4())
    suite = SimpleNamespace(
        test_cases=(SimpleNamespace(authorized_identity_id=user_id),),
        evaluation_tenant_id=selected_tenant,
    )
    validator = EvaluationCorpusValidator(
        actors, documents, versions, SimpleNamespace(), selected_tenant
    )
    with pytest.raises(ValueError, match="selected tenant"):
        await validator.validate(suite, manifest)
    versions.get_document_id.assert_not_awaited()
