"""Prompt text must come from the selected immutable query capability snapshots."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from document_insight.application.query.exceptions import QueryProfileUnavailableError
from document_insight.application.query.profile_resolver import QueryProfileResolver
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.configuration_snapshot.protocol import ConfigurationSnapshot
from document_insight.infrastructure.query_profile.protocol import ResolvedQueryProfile


@dataclass
class _QueryProfiles:
    profile: ResolvedQueryProfile

    async def get(self, profile_id: UUID) -> ResolvedQueryProfile | None:
        return self.profile if profile_id == self.profile.query_profile_id else None


@dataclass
class _CapabilityProfiles:
    profiles: dict[UUID, CapabilityProfile]

    async def get(self, profile_id: UUID) -> CapabilityProfile | None:
        return self.profiles.get(profile_id)


@dataclass
class _Snapshots:
    snapshots: dict[UUID, ConfigurationSnapshot]

    async def get(self, snapshot_id: UUID) -> ConfigurationSnapshot | None:
        return self.snapshots.get(snapshot_id)


def _resolver(generation_prompt: str | None) -> tuple[QueryProfileResolver, UUID]:
    query_id, embedding_id, ranker_id, generator_id = (uuid4() for _ in range(4))
    embedding_snapshot, ranker_snapshot, generator_snapshot, retrieval_snapshot = (
        uuid4() for _ in range(4)
    )
    generation_config = {
        "provider": "mistral",
        "model": "generator",
        "configuration_revision": "1",
        "prompt_revision": "1",
        "correction_prompt": "Correct references.",
        "response_schema_revision": "1",
        "temperature": 0.0,
        "max_output_tokens": 128,
    }
    if generation_prompt is not None:
        generation_config["system_prompt"] = generation_prompt
    return (
        QueryProfileResolver(
            _QueryProfiles(
                ResolvedQueryProfile(
                    query_id,
                    (uuid4(),),
                    (embedding_id,),
                    ranker_id,
                    generator_id,
                    retrieval_snapshot,
                )
            ),
            _CapabilityProfiles(
                {
                    embedding_id: CapabilityProfile(embedding_id, "embedding", embedding_snapshot),
                    ranker_id: CapabilityProfile(ranker_id, "reranking", ranker_snapshot),
                    generator_id: CapabilityProfile(generator_id, "generation", generator_snapshot),
                }
            ),
            _Snapshots(
                {
                    embedding_snapshot: ConfigurationSnapshot(
                        embedding_snapshot,
                        "embedding",
                        1,
                        {
                            "provider": "mistral",
                            "model": "embed",
                            "configuration_revision": "1",
                            "dimensions": 2,
                            "normalize": True,
                            "batch_size": 8,
                        },
                    ),
                    ranker_snapshot: ConfigurationSnapshot(
                        ranker_snapshot,
                        "reranking",
                        1,
                        {
                            "provider": "mistral",
                            "model": "ranker",
                            "configuration_revision": "1",
                            "prompt_revision": "1",
                            "system_prompt": "Rank from this profile.",
                            "response_schema_revision": "1",
                            "temperature": 0.0,
                            "max_output_tokens": 128,
                        },
                    ),
                    generator_snapshot: ConfigurationSnapshot(
                        generator_snapshot,
                        "generation",
                        1,
                        generation_config,
                    ),
                    retrieval_snapshot: ConfigurationSnapshot(
                        retrieval_snapshot,
                        "retrieval",
                        1,
                        {
                            "lexical_candidate_limit": 10,
                            "vector_candidate_limit": 10,
                            "rerank_candidate_limit": 10,
                            "rrf_k": 60,
                            "entity_match_boost": 0.1,
                            "insufficient_evidence_threshold": 0.5,
                            "min_citation_score": 0.35,
                        },
                    ),
                }
            ),
        ),
        query_id,
    )


@pytest.mark.anyio
async def test_query_profile_resolves_exact_prompt_text() -> None:
    resolver, query_id = _resolver("Answer from this profile.")

    profile = await resolver.resolve(query_id)

    assert profile.reranking.system_prompt == "Rank from this profile."
    assert profile.generation.system_prompt == "Answer from this profile."
    assert profile.generation.correction_prompt == "Correct references."


@pytest.mark.anyio
async def test_query_profile_without_prompt_is_unavailable() -> None:
    resolver, query_id = _resolver(None)

    with pytest.raises(QueryProfileUnavailableError):
        await resolver.resolve(query_id)
