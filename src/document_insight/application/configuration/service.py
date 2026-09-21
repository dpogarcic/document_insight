"""Resolve persisted capability profiles into typed worker configuration."""

from uuid import UUID

from pydantic import ValidationError

from document_insight.application.configuration.exceptions import InvalidProcessingProfileError
from document_insight.application.configuration.models import (
    Capability,
    ChunkingConfiguration,
    EmbeddingConfiguration,
    NerConfiguration,
    ResolvedIngestionProfile,
)
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfileRepository
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshot,
    ConfigurationSnapshotRepository,
)
from document_insight.infrastructure.ingestion_profile.protocol import IngestionProfileRepository


class IngestionProfileResolver:
    """Resolve exact non-secret configuration from immutable persisted IDs."""

    def __init__(
        self,
        ingestion_profiles: IngestionProfileRepository,
        capability_profiles: CapabilityProfileRepository,
        snapshots: ConfigurationSnapshotRepository,
    ) -> None:
        self._ingestion_profiles = ingestion_profiles
        self._capability_profiles = capability_profiles
        self._snapshots = snapshots

    async def resolve(self, ingestion_profile_id: UUID) -> ResolvedIngestionProfile:
        """Return typed NER, chunking, and embedding configuration for one bundle."""
        ingestion_profile = await self._ingestion_profiles.get(ingestion_profile_id)
        if ingestion_profile is None:
            raise InvalidProcessingProfileError
        ner_snapshot = await self._snapshot_for(ingestion_profile.ner_profile_id, Capability.NER)
        chunking_snapshot = await self._snapshot_for(
            ingestion_profile.chunking_profile_id, Capability.CHUNKING
        )
        embedding_snapshot = await self._snapshot_for(
            ingestion_profile.embedding_profile_id, Capability.EMBEDDING
        )
        try:
            ner = NerConfiguration.model_validate(ner_snapshot.configuration)
            chunking = ChunkingConfiguration.model_validate(chunking_snapshot.configuration)
            embedding = EmbeddingConfiguration.model_validate(embedding_snapshot.configuration)
        except ValidationError as error:
            raise InvalidProcessingProfileError from error
        return ResolvedIngestionProfile(
            ingestion_profile_id=ingestion_profile.ingestion_profile_id,
            ner_profile_id=ingestion_profile.ner_profile_id,
            chunking_profile_id=ingestion_profile.chunking_profile_id,
            lexical_profile_id=ingestion_profile.lexical_profile_id,
            embedding_profile_id=ingestion_profile.embedding_profile_id,
            ner=ner,
            chunking=chunking,
            embedding=embedding,
        )

    async def _snapshot_for(
        self, profile_id: UUID, expected_capability: Capability
    ) -> ConfigurationSnapshot:
        """Load one profile's snapshot and ensure it cannot impersonate another capability."""
        profile = await self._capability_profiles.get(profile_id)
        if profile is None or profile.capability != expected_capability.value:
            raise InvalidProcessingProfileError
        snapshot = await self._snapshots.get(profile.configuration_snapshot_id)
        if snapshot is None or snapshot.capability != expected_capability.value:
            raise InvalidProcessingProfileError
        return snapshot
