"""Manual platform approval of immutable RAG capability bundles."""

import json
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from document_insight.application.configuration.exceptions import (
    InvalidProfileProposalError,
    ProfileRevisionConflictError,
)
from document_insight.application.configuration.models import (
    Capability,
    ChunkingConfiguration,
    EmbeddingConfiguration,
    GenerationConfiguration,
    LexicalConfiguration,
    NerConfiguration,
    RerankingConfiguration,
    RetrievalConfiguration,
)
from document_insight.infrastructure.active_profile.protocol import ActiveProfileRepository
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfileRepository
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.index_generation.protocol import IndexGenerationRepository
from document_insight.infrastructure.ingestion_profile.protocol import (
    IngestionProfile,
    IngestionProfileRepository,
)
from document_insight.infrastructure.profile_activation.protocol import (
    CreateProfileActivation,
    ProfileActivationRepository,
)
from document_insight.infrastructure.query_profile.protocol import (
    QueryProfileRepository,
    ResolvedQueryProfile,
)

_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "ner": NerConfiguration,
    "chunking": ChunkingConfiguration,
    "lexical": LexicalConfiguration,
    "embedding": EmbeddingConfiguration,
    "reranking": RerankingConfiguration,
    "generation": GenerationConfiguration,
    "retrieval": RetrievalConfiguration,
}
_SECRET_KEYS = (
    "secret",
    "password",
    "api_key",
    "bearer_token",
    "access_token",
    "endpoint",
    "url",
    "credential",
)


class ProfileApprovalService:
    """Stage, validate, and explicitly activate platform configuration profiles."""

    def __init__(
        self,
        snapshots: ConfigurationSnapshotRepository,
        capabilities: CapabilityProfileRepository,
        ingestions: IngestionProfileRepository,
        queries: QueryProfileRepository,
        active: ActiveProfileRepository,
        generations: IndexGenerationRepository,
        activations: ProfileActivationRepository,
        transactions: TransactionManager,
        mistral_available: bool,
    ) -> None:
        self._snapshots = snapshots
        self._capabilities = capabilities
        self._ingestions = ingestions
        self._queries = queries
        self._active = active
        self._generations = generations
        self._activations = activations
        self._transactions = transactions
        self._mistral_available = mistral_available

    async def create_capability(
        self, capability: Capability, name: str, configuration: dict[str, Any]
    ) -> UUID:
        """Stage an immutable draft; a separate validation approves it for bundles."""
        if not name.strip() or len(name) > 120:
            raise InvalidProfileProposalError("Profile name must be 1 to 120 characters")
        canonical = self._validate_configuration(
            capability.value, configuration, require_runtime=False
        )
        fingerprint = self._fingerprint(canonical)
        profile_id = uuid4()
        async with self._transactions.begin():
            snapshot = await self._snapshots.get_by_fingerprint(capability.value, fingerprint)
            if snapshot is None:
                snapshot_id = uuid4()
                await self._snapshots.create(snapshot_id, capability.value, fingerprint, canonical)
            else:
                snapshot_id = snapshot.snapshot_id
            await self._capabilities.create(profile_id, capability.value, name, snapshot_id)
        return profile_id

    async def validate_capability(self, profile_id: UUID) -> None:
        """Approve a draft only after deployed adapter and runtime checks succeed."""
        async with self._transactions.begin():
            profile = await self._capabilities.get(profile_id)
            if profile is None or profile.status != "draft":
                raise InvalidProfileProposalError("A draft capability profile is required")
            snapshot = await self._snapshots.get(profile.configuration_snapshot_id)
            if snapshot is None or snapshot.capability != profile.capability:
                raise InvalidProfileProposalError("Capability snapshot is unavailable")
            self._validate_configuration(profile.capability, snapshot.configuration)
            await self._capabilities.validate(profile_id)

    async def create_ingestion(
        self, ner: UUID, chunking: UUID, lexical: UUID, embedding: UUID
    ) -> UUID:
        """Stage an immutable bundle of approved ingestion capabilities."""
        profile_id = uuid4()
        async with self._transactions.begin():
            for identifier, capability in (
                (ner, Capability.NER),
                (chunking, Capability.CHUNKING),
                (lexical, Capability.LEXICAL),
                (embedding, Capability.EMBEDDING),
            ):
                await self._require_validated(identifier, capability)
            await self._ingestions.create(
                IngestionProfile(profile_id, ner, chunking, lexical, embedding)
            )
        return profile_id

    async def create_query(
        self,
        lexical_ids: tuple[UUID, ...],
        embedding_ids: tuple[UUID, ...],
        reranker: UUID,
        generation: UUID,
        retrieval_configuration: dict[str, Any],
    ) -> UUID:
        """Stage explicit old and new read cohorts with approved query capabilities."""
        if (
            not lexical_ids
            or not embedding_ids
            or len(set(lexical_ids)) != len(lexical_ids)
            or len(set(embedding_ids)) != len(embedding_ids)
        ):
            raise InvalidProfileProposalError("Read cohorts must be nonempty and unique")
        canonical = self._validate_configuration("retrieval", retrieval_configuration)
        fingerprint = self._fingerprint(canonical)
        profile_id = uuid4()
        async with self._transactions.begin():
            for identifier in lexical_ids:
                await self._require_validated(identifier, Capability.LEXICAL)
            for identifier in embedding_ids:
                await self._require_validated(identifier, Capability.EMBEDDING)
            await self._require_validated(reranker, Capability.RERANKING)
            await self._require_validated(generation, Capability.GENERATION)
            snapshot = await self._snapshots.get_by_fingerprint("retrieval", fingerprint)
            if snapshot is None:
                snapshot_id = uuid4()
                await self._snapshots.create(snapshot_id, "retrieval", fingerprint, canonical)
            else:
                snapshot_id = snapshot.snapshot_id
            await self._queries.create(
                ResolvedQueryProfile(
                    profile_id, lexical_ids, embedding_ids, reranker, generation, snapshot_id
                )
            )
        return profile_id

    async def activate(
        self, kind: str, profile_id: UUID, expected_revision: int, actor_id: UUID, reason: str
    ) -> int:
        """Atomically switch a reviewed pointer and append an audit record."""
        if kind not in ("ingestion", "query") or not reason.strip() or len(reason) > 512:
            raise InvalidProfileProposalError("Kind or activation reason is invalid")
        async with self._transactions.begin():
            # Lock both pointers in a stable order. Otherwise concurrent ingestion and
            # query switches could each validate against the other's previous value.
            active_ingestion = await self._active.lock("platform", "ingestion")
            active_query = await self._active.lock("platform", "query")
            current = active_ingestion if kind == "ingestion" else active_query
            if current is None or current.revision != expected_revision:
                raise ProfileRevisionConflictError
            if current.profile_id == profile_id:
                raise InvalidProfileProposalError("Profile is already active")
            if kind == "ingestion":
                target = await self._require_ingestion(profile_id)
                if active_query is None:
                    raise InvalidProfileProposalError("No active query profile")
                query = await self._require_query(active_query.profile_id)
                self._require_cohorts(query, (target,))
            else:
                target_query = await self._require_query(profile_id)
                ingestion_ids = set(await self._generations.referenced_ingestion_profile_ids())
                if active_ingestion is not None:
                    ingestion_ids.add(active_ingestion.profile_id)
                ingestions = tuple(
                    [await self._require_ingestion(identifier) for identifier in ingestion_ids]
                )
                self._require_cohorts(target_query, ingestions)
            await self._active.activate("platform", kind, profile_id, current.revision)
            await self._activations.create(
                CreateProfileActivation(
                    "platform",
                    kind,
                    current.profile_id,
                    profile_id,
                    actor_id,
                    reason.strip(),
                    current.revision + 1,
                )
            )
            return current.revision + 1

    async def _require_validated(self, profile_id: UUID, capability: Capability) -> None:
        profile = await self._capabilities.get(profile_id)
        if (
            profile is None
            or profile.capability != capability.value
            or profile.status != "validated"
        ):
            raise InvalidProfileProposalError(f"Validated {capability.value} profile required")
        snapshot = await self._snapshots.get(profile.configuration_snapshot_id)
        if snapshot is None or snapshot.capability != capability.value:
            raise InvalidProfileProposalError("Capability snapshot is unavailable")
        self._validate_configuration(capability.value, snapshot.configuration)

    async def _require_ingestion(self, profile_id: UUID) -> IngestionProfile:
        profile = await self._ingestions.get(profile_id)
        if profile is None:
            raise InvalidProfileProposalError("Ingestion bundle is unavailable")
        for identifier, capability in (
            (profile.ner_profile_id, Capability.NER),
            (profile.chunking_profile_id, Capability.CHUNKING),
            (profile.lexical_profile_id, Capability.LEXICAL),
            (profile.embedding_profile_id, Capability.EMBEDDING),
        ):
            await self._require_validated(identifier, capability)
        return profile

    async def _require_query(self, profile_id: UUID) -> ResolvedQueryProfile:
        profile = await self._queries.get(profile_id)
        if profile is None or not profile.lexical_profile_ids or not profile.embedding_profile_ids:
            raise InvalidProfileProposalError("Query bundle is unavailable")
        for identifier in profile.lexical_profile_ids:
            await self._require_validated(identifier, Capability.LEXICAL)
        for identifier in profile.embedding_profile_ids:
            await self._require_validated(identifier, Capability.EMBEDDING)
        await self._require_validated(profile.reranker_profile_id, Capability.RERANKING)
        await self._require_validated(profile.generation_profile_id, Capability.GENERATION)
        snapshot = await self._snapshots.get(profile.retrieval_snapshot_id)
        if snapshot is None or snapshot.capability != "retrieval":
            raise InvalidProfileProposalError("Retrieval snapshot is unavailable")
        self._validate_configuration("retrieval", snapshot.configuration)
        return profile

    @staticmethod
    def _require_cohorts(
        query: ResolvedQueryProfile, ingestions: tuple[IngestionProfile, ...]
    ) -> None:
        """Prevent activation from hiding ready old indexes or new ingestions."""
        for ingestion in ingestions:
            if (
                ingestion.lexical_profile_id not in query.lexical_profile_ids
                or ingestion.embedding_profile_id not in query.embedding_profile_ids
            ):
                raise InvalidProfileProposalError(
                    "Query cohorts must include every ready and active ingestion profile"
                )

    def _validate_configuration(
        self, capability: str, raw: dict[str, Any], *, require_runtime: bool = True
    ) -> dict[str, Any]:
        """Validate exact supported behavior and exclude runtime credentials."""
        if capability not in _CONFIG_MODELS or any(
            any(secret in key.casefold() for secret in _SECRET_KEYS) for key in raw
        ):
            raise InvalidProfileProposalError("Unsupported or secret-bearing configuration")
        try:
            value = _CONFIG_MODELS[capability].model_validate(raw)
        except ValidationError as error:
            raise InvalidProfileProposalError("Configuration schema is invalid") from error
        if require_runtime and isinstance(value, NerConfiguration) and value.provider != "spacy":
            raise InvalidProfileProposalError("Unsupported NER provider")
        if (
            require_runtime
            and isinstance(value, ChunkingConfiguration)
            and value.implementation != "page_window"
        ):
            raise InvalidProfileProposalError("Unsupported chunker")
        if (
            require_runtime
            and isinstance(value, LexicalConfiguration)
            and (value.implementation != "postgres_fts" or value.configuration != "simple")
        ):
            raise InvalidProfileProposalError("Unsupported lexical index")
        if isinstance(
            value, (EmbeddingConfiguration, RerankingConfiguration, GenerationConfiguration)
        ):
            if require_runtime and (value.provider != "mistral" or not self._mistral_available):
                raise InvalidProfileProposalError(
                    "Mistral adapter or runtime credential unavailable"
                )
        return value.model_dump(mode="json")

    @staticmethod
    def _fingerprint(configuration: dict[str, Any]) -> str:
        encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()
