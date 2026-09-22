"""Resolve immutable query-profile records into typed RAG configuration."""

from uuid import UUID

from pydantic import ValidationError

from document_insight.application.configuration.models import (
    Capability,
    EmbeddingConfiguration,
    GenerationConfiguration,
    RerankingConfiguration,
    ResolvedQueryProfile,
    RetrievalConfiguration,
)
from document_insight.application.query.exceptions import QueryProfileUnavailableError
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfileRepository
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshot,
    ConfigurationSnapshotRepository,
)
from document_insight.infrastructure.query_profile.protocol import QueryProfileRepository


class QueryProfileResolver:
    """Load and validate the full immutable configuration for a query execution."""

    def __init__(
        self,
        query_profiles: QueryProfileRepository,
        capability_profiles: CapabilityProfileRepository,
        snapshots: ConfigurationSnapshotRepository,
    ) -> None:
        self._query_profiles = query_profiles
        self._capability_profiles = capability_profiles
        self._snapshots = snapshots

    async def resolve(self, query_profile_id: UUID) -> ResolvedQueryProfile:
        """Return fully typed configuration or a safe unavailable error."""
        profile = await self._query_profiles.get(query_profile_id)
        if profile is None or not profile.lexical_profile_ids or not profile.embedding_profile_ids:
            raise QueryProfileUnavailableError
        try:
            embeddings_list: list[tuple[UUID, EmbeddingConfiguration]] = []
            for profile_id in profile.embedding_profile_ids:
                snapshot = await self._snapshot_for(profile_id, Capability.EMBEDDING)
                embeddings_list.append(
                    (profile_id, EmbeddingConfiguration.model_validate(snapshot.configuration))
                )
            embeddings = tuple(embeddings_list)
            reranking = RerankingConfiguration.model_validate(
                (await self._snapshot_for(profile.reranker_profile_id, Capability.RERANKING)).configuration
            )
            generation = GenerationConfiguration.model_validate(
                (await self._snapshot_for(profile.generation_profile_id, Capability.GENERATION)).configuration
            )
            retrieval_snapshot = await self._snapshots.get(profile.retrieval_snapshot_id)
            if retrieval_snapshot is None or retrieval_snapshot.capability != "retrieval":
                raise QueryProfileUnavailableError
            retrieval = RetrievalConfiguration.model_validate(retrieval_snapshot.configuration)
        except ValidationError as error:
            raise QueryProfileUnavailableError from error
        return ResolvedQueryProfile(
            profile.query_profile_id,
            profile.lexical_profile_ids,
            profile.embedding_profile_ids,
            embeddings,
            reranking,
            generation,
            retrieval,
        )

    async def _snapshot_for(
        self, profile_id: UUID, expected_capability: Capability
    ) -> ConfigurationSnapshot:
        """Validate a capability profile and its immutable snapshot together."""
        profile = await self._capability_profiles.get(profile_id)
        if profile is None or profile.capability != expected_capability.value:
            raise QueryProfileUnavailableError
        snapshot = await self._snapshots.get(profile.configuration_snapshot_id)
        if snapshot is None or snapshot.capability != expected_capability.value:
            raise QueryProfileUnavailableError
        return snapshot
