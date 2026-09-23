"""Selectable-query filtering excludes profiles built on retired capabilities."""

from uuid import uuid4

from document_insight.application.configuration.catalog import ProfileCatalog
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.query_profile.protocol import ResolvedQueryProfile


def _query(reranker_id, generation_id) -> ResolvedQueryProfile:  # type: ignore[no-untyped-def]
    return ResolvedQueryProfile(uuid4(), (uuid4(),), (uuid4(),), reranker_id, generation_id, uuid4())


def test_selectable_queries_excludes_a_profile_with_a_retired_reranker() -> None:
    retired_reranker = uuid4()
    working_generation = uuid4()
    capabilities = (
        CapabilityProfile(retired_reranker, "reranking", uuid4(), status="retired"),
        CapabilityProfile(working_generation, "generation", uuid4(), status="validated"),
    )
    query = _query(retired_reranker, working_generation)
    catalog = ProfileCatalog(capabilities, (), (query,), None, None)
    assert catalog.selectable_queries == ()


def test_selectable_queries_excludes_a_profile_with_a_retired_generator() -> None:
    working_reranker = uuid4()
    retired_generation = uuid4()
    capabilities = (
        CapabilityProfile(working_reranker, "reranking", uuid4(), status="validated"),
        CapabilityProfile(retired_generation, "generation", uuid4(), status="retired"),
    )
    query = _query(working_reranker, retired_generation)
    catalog = ProfileCatalog(capabilities, (), (query,), None, None)
    assert catalog.selectable_queries == ()


def test_selectable_queries_keeps_a_profile_backed_by_validated_capabilities() -> None:
    reranker = uuid4()
    generation = uuid4()
    capabilities = (
        CapabilityProfile(reranker, "reranking", uuid4(), status="validated"),
        CapabilityProfile(generation, "generation", uuid4(), status="validated"),
    )
    query = _query(reranker, generation)
    catalog = ProfileCatalog(capabilities, (), (query,), None, None)
    assert catalog.selectable_queries == (query,)
