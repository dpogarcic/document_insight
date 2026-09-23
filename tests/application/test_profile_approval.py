"""Operator approval and backward-compatible cohort activation rules."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from document_insight.application.configuration.approval import ProfileApprovalService
from document_insight.application.configuration.exceptions import (
    InvalidProfileProposalError,
    ProfileRevisionConflictError,
)
from document_insight.application.configuration.models import Capability
from document_insight.application.evaluation.models import CorpusVariant, EvaluationCorpusManifest
from document_insight.infrastructure.active_profile.protocol import ActiveProfile
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.configuration_snapshot.protocol import ConfigurationSnapshot
from document_insight.infrastructure.ingestion_profile.protocol import IngestionProfile
from document_insight.infrastructure.query_profile.protocol import ResolvedQueryProfile


class Transactions:
    """No-op transaction boundary for isolated service tests."""

    @asynccontextmanager
    async def begin(self):  # type: ignore[no-untyped-def]
        yield


def _service(
    ingestions: dict[UUID, IngestionProfile],
    queries: dict[UUID, ResolvedQueryProfile],
    active_ingestion: UUID,
    active_query: UUID,
    ready_ids: tuple[UUID, ...] = (),
) -> tuple[ProfileApprovalService, SimpleNamespace]:
    """Create a boundary fake with exact persisted capability-to-snapshot mappings."""
    capabilities: dict[UUID, CapabilityProfile] = {}
    snapshots: dict[UUID, ConfigurationSnapshot] = {}
    specs = {
        "ner": {
            "provider": "spacy",
            "english_model": "en_core_web_sm",
            "croatian_model": "hr_core_news_sm",
            "model_revision": "1",
        },
        "chunking": {
            "implementation": "page_window",
            "implementation_revision": "1",
            "max_chars": 800,
            "overlap_chars": 100,
        },
        "lexical": {
            "implementation": "postgres_fts",
            "configuration": "simple",
            "implementation_revision": "1",
        },
        "embedding": {
            "provider": "mistral",
            "model": "mistral-embed",
            "configuration_revision": "1",
            "dimensions": 1024,
            "normalize": True,
            "batch_size": 32,
        },
        "reranking": {
            "provider": "mistral",
            "model": "model",
            "configuration_revision": "1",
            "prompt_revision": "1",
            "system_prompt": "Rank evidence",
            "response_schema_revision": "1",
            "temperature": 0,
            "max_output_tokens": 128,
        },
        "generation": {
            "provider": "mistral",
            "model": "model",
            "configuration_revision": "1",
            "prompt_revision": "1",
            "system_prompt": "Answer from evidence",
            "correction_prompt": "Fix citations",
            "response_schema_revision": "1",
            "temperature": 0,
            "max_output_tokens": 128,
        },
        "retrieval": {
            "lexical_candidate_limit": 10,
            "vector_candidate_limit": 10,
            "rerank_candidate_limit": 10,
            "rrf_k": 60,
            "entity_match_boost": 0.1,
            "insufficient_evidence_threshold": 0.4,
            "min_citation_score": 0.3,
        },
    }

    def register(identifier: UUID, capability: str) -> None:
        snapshot_id = uuid4()
        capabilities[identifier] = CapabilityProfile(
            identifier, capability, snapshot_id, "validated"
        )
        snapshots[snapshot_id] = ConfigurationSnapshot(
            snapshot_id, capability, 1, specs[capability]
        )

    for ingestion in ingestions.values():
        for identifier, capability in (
            (ingestion.ner_profile_id, "ner"),
            (ingestion.chunking_profile_id, "chunking"),
            (ingestion.lexical_profile_id, "lexical"),
            (ingestion.embedding_profile_id, "embedding"),
        ):
            register(identifier, capability)
    for query in queries.values():
        for identifier in query.lexical_profile_ids:
            register(identifier, "lexical")
        for identifier in query.embedding_profile_ids:
            register(identifier, "embedding")
        register(query.reranker_profile_id, "reranking")
        register(query.generation_profile_id, "generation")
        snapshots[query.retrieval_snapshot_id] = ConfigurationSnapshot(
            query.retrieval_snapshot_id, "retrieval", 1, specs["retrieval"]
        )
    state = SimpleNamespace(
        snapshots=SimpleNamespace(
            get=AsyncMock(side_effect=snapshots.get),
            get_by_fingerprint=AsyncMock(return_value=None),
            create=AsyncMock(),
        ),
        capabilities=SimpleNamespace(
            get=AsyncMock(side_effect=capabilities.get),
            create=AsyncMock(),
            validate=AsyncMock(),
        ),
        ingestions=SimpleNamespace(get=AsyncMock(side_effect=ingestions.get), create=AsyncMock()),
        queries=SimpleNamespace(get=AsyncMock(side_effect=queries.get), create=AsyncMock()),
        active=SimpleNamespace(
            lock=AsyncMock(
                side_effect=lambda scope, kind: ActiveProfile(
                    active_ingestion if kind == "ingestion" else active_query, 1
                )
            ),
            get_ingestion_profile_id=AsyncMock(return_value=active_ingestion),
            get_query_profile_id=AsyncMock(return_value=active_query),
            activate=AsyncMock(),
            create_evaluation_ingestion=AsyncMock(),
        ),
        generations=SimpleNamespace(
            referenced_ingestion_profile_ids=AsyncMock(return_value=ready_ids)
        ),
        activations=SimpleNamespace(create=AsyncMock()),
    )
    service = ProfileApprovalService(
        state.snapshots,
        state.capabilities,
        state.ingestions,
        state.queries,
        state.active,
        state.generations,
        state.activations,
        Transactions(),
        True,
    )
    return service, state


@pytest.mark.anyio
async def test_test_tenant_can_select_candidate_ingestion_without_platform_switch() -> None:
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
    )
    tenant_id = uuid4()
    service._evaluation_tenant_id = tenant_id
    state.active.lock.side_effect = lambda scope, kind: (
        None if scope == f"evaluation:{tenant_id}" else ActiveProfile(old.ingestion_profile_id, 1)
    )
    revision = await service.select_evaluation_ingestion(
        tenant_id,
        new.ingestion_profile_id,
        0,
        uuid4(),
        "test candidate",
    )
    assert revision == 1
    state.active.create_evaluation_ingestion.assert_awaited_once_with(
        f"evaluation:{tenant_id}", new.ingestion_profile_id
    )
    state.active.activate.assert_not_awaited()

    with pytest.raises(InvalidProfileProposalError, match="isolated test tenant"):
        await service.select_evaluation_ingestion(
            uuid4(), new.ingestion_profile_id, 0, uuid4(), "wrong tenant"
        )


@pytest.mark.anyio
async def test_query_activation_requires_approved_current_baseline_comparison() -> None:
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
    )
    run_id = uuid4()
    tenant_id = uuid4()
    service._evaluation_tenant_id = tenant_id
    runs = SimpleNamespace(
        list_runs=AsyncMock(
            return_value=(
                SimpleNamespace(
                    run_id=run_id,
                    evaluation_mode="query",
                    comparison_valid=True,
                    baseline_profile_ids=(old_query.query_profile_id,),
                    candidate_profile_ids=(combined.query_profile_id,),
                    corpus_manifest={"evaluation_tenant_id": str(tenant_id)},
                ),
            )
        ),
    )
    service._evaluation_runs = runs
    reviews = SimpleNamespace(get_for_run=AsyncMock(return_value=None))
    service._evaluation_reviews = reviews
    with pytest.raises(InvalidProfileProposalError, match="approved evaluation"):
        await service.activate("query", combined.query_profile_id, 1, uuid4(), "rollout")
    state.active.activate.assert_not_awaited()
    reviews.get_for_run.return_value = SimpleNamespace(decision="approve")
    await service.activate("query", combined.query_profile_id, 1, uuid4(), "rollout")
    state.active.activate.assert_awaited_once()


@pytest.mark.anyio
async def test_ingestion_activation_requires_reviewed_test_copy_comparison() -> None:
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        combined.query_profile_id,
    )
    version_id, copy_id = uuid4(), uuid4()
    manifest = EvaluationCorpusManifest(
        "a" * 64,
        CorpusVariant((version_id,), {version_id: version_id}),
        CorpusVariant((copy_id,), {copy_id: version_id}),
        combined.query_profile_id,
        combined.query_profile_id,
        old.ingestion_profile_id,
        new.ingestion_profile_id,
    )
    tenant_id = uuid4()
    service._evaluation_tenant_id = tenant_id
    runs = SimpleNamespace(
        list_runs=AsyncMock(
            return_value=(
                SimpleNamespace(
                    run_id=uuid4(),
                    evaluation_mode="ingestion",
                    comparison_valid=True,
                    corpus_manifest={**manifest.to_json(), "evaluation_tenant_id": str(tenant_id)},
                ),
            )
        ),
    )
    service._evaluation_runs = runs
    reviews = SimpleNamespace(get_for_run=AsyncMock(return_value=None))
    service._evaluation_reviews = reviews
    with pytest.raises(InvalidProfileProposalError, match="ingestion evaluation"):
        await service.activate("ingestion", new.ingestion_profile_id, 1, uuid4(), "rollout")
    reviews.get_for_run.return_value = SimpleNamespace(decision="approve")
    await service.activate("ingestion", new.ingestion_profile_id, 1, uuid4(), "rollout")
    state.active.activate.assert_awaited_once()


def _fixtures() -> tuple[
    IngestionProfile, IngestionProfile, ResolvedQueryProfile, ResolvedQueryProfile
]:
    shared_ner, shared_chunking, ranker, generator, retrieval = (uuid4() for _ in range(5))
    old = IngestionProfile(uuid4(), shared_ner, shared_chunking, uuid4(), uuid4())
    new = IngestionProfile(uuid4(), shared_ner, shared_chunking, uuid4(), uuid4())
    old_query = ResolvedQueryProfile(
        uuid4(),
        (old.lexical_profile_id,),
        (old.embedding_profile_id,),
        ranker,
        generator,
        retrieval,
    )
    combined = ResolvedQueryProfile(
        uuid4(),
        (old.lexical_profile_id, new.lexical_profile_id),
        (old.embedding_profile_id, new.embedding_profile_id),
        ranker,
        generator,
        retrieval,
    )
    return old, new, old_query, combined


@pytest.mark.anyio
async def test_new_ingestion_requires_query_profile_with_both_embedding_cohorts() -> None:
    """A profile switch cannot make new documents invisible or lose old indexed evidence."""
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
        (old.ingestion_profile_id,),
    )
    actor = uuid4()
    with pytest.raises(InvalidProfileProposalError, match="cohorts"):
        await service.activate("ingestion", new.ingestion_profile_id, 1, actor, "new model")
    state.active.activate.assert_not_awaited()

    await service.activate("query", combined.query_profile_id, 1, actor, "read both cohorts")
    state.active.lock.side_effect = lambda scope, kind: ActiveProfile(
        old.ingestion_profile_id if kind == "ingestion" else combined.query_profile_id,
        1 if kind == "ingestion" else 2,
    )
    await service.activate("ingestion", new.ingestion_profile_id, 1, actor, "new model")
    assert state.active.activate.await_count == 2
    assert state.activations.create.await_count == 2


@pytest.mark.anyio
async def test_query_activation_cannot_drop_ready_legacy_embedding_cohort() -> None:
    """Even after new ingestion is active, earlier ready generations remain readable."""
    old, new, _, combined = _fixtures()
    new_only = ResolvedQueryProfile(
        uuid4(),
        (new.lexical_profile_id,),
        (new.embedding_profile_id,),
        combined.reranker_profile_id,
        combined.generation_profile_id,
        combined.retrieval_snapshot_id,
    )
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {combined.query_profile_id: combined, new_only.query_profile_id: new_only},
        new.ingestion_profile_id,
        combined.query_profile_id,
        (old.ingestion_profile_id,),
    )
    with pytest.raises(InvalidProfileProposalError, match="cohorts"):
        await service.activate("query", new_only.query_profile_id, 1, uuid4(), "retire old")
    state.active.activate.assert_not_awaited()


@pytest.mark.anyio
async def test_stale_revision_does_not_switch_profile() -> None:
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
    )
    with pytest.raises(ProfileRevisionConflictError):
        await service.activate("query", combined.query_profile_id, 0, uuid4(), "stale")
    state.active.activate.assert_not_awaited()


@pytest.mark.anyio
async def test_draft_is_not_approved_and_secret_is_rejected() -> None:
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
    )
    with pytest.raises(InvalidProfileProposalError, match="secret"):
        await service.create_capability(
            Capability.EMBEDDING,
            "bad",
            {
                "provider": "mistral",
                "api_key": "must-not-store",
            },
        )
    state.snapshots.create.assert_not_awaited()
    state.capabilities.get.side_effect = lambda identifier: CapabilityProfile(
        identifier, "embedding", uuid4(), "draft"
    )
    with pytest.raises(InvalidProfileProposalError, match="Validated"):
        await service.create_ingestion(
            old.ner_profile_id,
            old.chunking_profile_id,
            old.lexical_profile_id,
            old.embedding_profile_id,
        )


@pytest.mark.anyio
async def test_unsupported_provider_can_be_staged_but_not_approved() -> None:
    """Deploying an adapter can follow proposal creation without activating it."""
    old, new, old_query, combined = _fixtures()
    service, state = _service(
        {old.ingestion_profile_id: old, new.ingestion_profile_id: new},
        {old_query.query_profile_id: old_query, combined.query_profile_id: combined},
        old.ingestion_profile_id,
        old_query.query_profile_id,
    )
    config = {
        "provider": "future-provider",
        "model": "future-embed",
        "configuration_revision": "1",
        "dimensions": 1024,
        "normalize": True,
        "batch_size": 16,
    }
    profile_id = await service.create_capability(Capability.EMBEDDING, "future-v1", config)
    state.capabilities.create.assert_awaited_once()
    snapshot_id = state.capabilities.create.await_args.args[3]
    state.capabilities.get.side_effect = lambda identifier: CapabilityProfile(
        identifier, "embedding", snapshot_id, "draft"
    )
    state.snapshots.get.side_effect = lambda identifier: ConfigurationSnapshot(
        identifier, "embedding", 1, config
    )
    with pytest.raises(InvalidProfileProposalError, match="adapter"):
        await service.validate_capability(profile_id)
    state.capabilities.validate.assert_not_awaited()
