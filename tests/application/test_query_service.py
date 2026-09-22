"""Unit tests for authorization-first hybrid RAG."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.configuration.models import (
    EmbeddingConfiguration,
    GenerationConfiguration,
    RerankingConfiguration,
    ResolvedQueryProfile,
    RetrievalConfiguration,
)
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.exceptions import QueryProfileUnavailableError
from document_insight.application.query.service import QueryPreparationService
from document_insight.infrastructure.generation.protocol import GroundedAnswer, GroundingPassage
from document_insight.infrastructure.reranker.protocol import RerankInput, RerankScore
from document_insight.infrastructure.retrieval.protocol import (
    EntityMatch,
    RetrievalScope,
    RetrievedChunk,
)


@dataclass
class ActiveProfiles:
    profile_id: UUID | None

    async def get_query_profile_id(self, scope: str) -> UUID | None:
        return self.profile_id


@dataclass
class Departments:
    ids: tuple[UUID, ...]

    async def list_all_ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        return self.ids


@dataclass
class Profiles:
    value: ResolvedQueryProfile

    async def resolve(self, profile_id: UUID) -> ResolvedQueryProfile:
        if profile_id != self.value.query_profile_id:
            raise QueryProfileUnavailableError
        return self.value


@dataclass
class Retrieval:
    chunk: RetrievedChunk | None
    additional_chunk: RetrievedChunk | None = None
    scopes: list[RetrievalScope] = field(default_factory=list)

    async def find_entity_matches(
        self, scope: RetrievalScope, filter_text: str, limit: int
    ) -> tuple[EntityMatch, ...]:
        self.scopes.append(scope)
        return (
            ()
            if self.chunk is None
            else (EntityMatch(self.chunk.document_version_id, "Acme", "ORG"),)
        )

    async def lexical_search(
        self, scope: RetrievalScope, lexical_profile_id: UUID, query_text: str, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        self.scopes.append(scope)
        return tuple(chunk for chunk in (self.chunk, self.additional_chunk) if chunk is not None)

    async def vector_search(
        self,
        scope: RetrievalScope,
        embedding_profile_id: UUID,
        vector: tuple[float, ...],
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        self.scopes.append(scope)
        return () if self.chunk is None else (self.chunk,)


class Embedder:
    async def embed(
        self, texts: tuple[str, ...], configuration: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        return ((1.0, 0.0),)


class Embedders:
    def create(self, configuration: EmbeddingConfiguration) -> Embedder:
        return Embedder()


class Reranker:
    scores = (0.9,)

    async def rerank(
        self,
        question: str,
        candidates: tuple[RerankInput, ...],
        configuration: RerankingConfiguration,
    ) -> tuple[RerankScore, ...]:
        return tuple(
            RerankScore(item.chunk_id, self.scores[index]) for index, item in enumerate(candidates)
        )


class Rerankers:
    def create(self, configuration: RerankingConfiguration) -> Reranker:
        return Reranker()


class Generator:
    received_passage_ids: tuple[UUID, ...] = ()

    async def generate(
        self,
        question: str,
        passages: tuple[GroundingPassage, ...],
        configuration: GenerationConfiguration,
    ) -> GroundedAnswer:
        type(self).received_passage_ids = tuple(passage.chunk_id for passage in passages)
        return GroundedAnswer("The contract renews annually.", (passages[0].chunk_id,))


class Generators:
    def create(self, configuration: GenerationConfiguration) -> Generator:
        return Generator()


def build_profile(profile_id: UUID) -> ResolvedQueryProfile:
    embedding_id = uuid4()
    return ResolvedQueryProfile(
        profile_id,
        (uuid4(),),
        (embedding_id,),
        (
            (
                embedding_id,
                EmbeddingConfiguration(
                    provider="mistral",
                    model="embed",
                    configuration_revision="1",
                    dimensions=2,
                    normalize=True,
                    batch_size=8,
                ),
            ),
        ),
        RerankingConfiguration(
            provider="mistral",
            model="rerank",
            configuration_revision="1",
            prompt_revision="1",
            response_schema_revision="1",
            temperature=0.0,
            max_output_tokens=128,
        ),
        GenerationConfiguration(
            provider="mistral",
            model="generate",
            configuration_revision="1",
            prompt_revision="1",
            response_schema_revision="1",
            temperature=0.0,
            max_output_tokens=128,
        ),
        RetrievalConfiguration(
            lexical_candidate_limit=10,
            vector_candidate_limit=10,
            rerank_candidate_limit=10,
            rrf_k=60,
            entity_match_boost=0.1,
            insufficient_evidence_threshold=0.5,
            min_citation_score=0.35,
        ),
    )


def build_service(
    profile_id: UUID | None,
    department_ids: tuple[UUID, ...],
    chunk: RetrievedChunk | None,
    additional_chunk: RetrievedChunk | None = None,
) -> tuple[QueryPreparationService, Retrieval]:
    retrieval = Retrieval(chunk, additional_chunk)
    active_profile_id = profile_id or uuid4()
    return QueryPreparationService(
        active_profiles=ActiveProfiles(profile_id),
        profile_resolver=Profiles(build_profile(active_profile_id)),
        departments=Departments(department_ids),
        retrieval=retrieval,
        embedders=Embedders(),
        rerankers=Rerankers(),
        generators=Generators(),
    ), retrieval


@pytest.mark.anyio
async def test_query_applies_the_same_trusted_scope_to_every_retrieval_branch() -> None:
    tenant_id, finance_id, legal_id, profile_id = (uuid4() for _ in range(4))
    chunk = RetrievedChunk(uuid4(), uuid4(), uuid4(), "Contract", "Annual renewal.", 2, 0.8)
    query_service, retrieval = build_service(profile_id, (finance_id, legal_id), chunk)
    result = await query_service.query(
        PrepareQueryCommand(
            "When does it renew?",
            "Acme",
            5,
            AuthorizationContext(uuid4(), tenant_id, (finance_id,), UserRole.TENANT_ADMIN),
        )
    )
    assert result.citations[0].chunk_id == chunk.chunk_id
    assert result.entities[0].text == "Acme"
    assert all(scope.department_ids == (finance_id, legal_id) for scope in retrieval.scopes)
    assert all(scope.tenant_id == tenant_id for scope in retrieval.scopes)


@pytest.mark.anyio
async def test_query_returns_insufficient_evidence_without_generation() -> None:
    tenant_id, department_id, profile_id = (uuid4() for _ in range(3))
    query_service, _ = build_service(profile_id, (department_id,), None)
    result = await query_service.query(
        PrepareQueryCommand(
            "What changed?",
            None,
            5,
            AuthorizationContext(uuid4(), tenant_id, (department_id,), UserRole.VIEWER),
        )
    )
    assert result.confidence == 0.0
    assert result.citations == ()


@pytest.mark.anyio
async def test_query_does_not_generate_from_passages_below_the_citation_floor() -> None:
    """Weak reranked passages never become model context or displayed citations."""
    tenant_id, department_id, profile_id = (uuid4() for _ in range(3))
    chunk = RetrievedChunk(uuid4(), uuid4(), uuid4(), "Contract", "Annual renewal.", 2, 0.8)
    weak_chunk = RetrievedChunk(uuid4(), uuid4(), uuid4(), "Old contract", "Old terms.", 3, 0.5)
    query_service, _ = build_service(profile_id, (department_id,), chunk, weak_chunk)
    Reranker.scores = (0.9, 0.34)
    Generator.received_passage_ids = ()

    result = await query_service.query(
        PrepareQueryCommand(
            "When does it renew?",
            None,
            5,
            AuthorizationContext(uuid4(), tenant_id, (department_id,), UserRole.VIEWER),
        )
    )

    assert result.citations[0].chunk_id == chunk.chunk_id
    assert Generator.received_passage_ids == (chunk.chunk_id,)
    Reranker.scores = (0.9,)


@pytest.mark.anyio
async def test_prepare_requires_an_explicit_active_query_profile() -> None:
    query_service, _ = build_service(None, (), None)
    with pytest.raises(QueryProfileUnavailableError):
        await query_service.prepare(
            PrepareQueryCommand(
                "Question", None, 5, AuthorizationContext(uuid4(), uuid4(), (), UserRole.VIEWER)
            )
        )
