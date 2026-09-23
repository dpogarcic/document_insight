"""Execute authorization-first hybrid retrieval and evidence-grounded generation."""

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import UUID

from document_insight.application.auth.models import UserRole
from document_insight.application.configuration.models import (
    ResolvedQueryProfile,
    RetrievalConfiguration,
)
from document_insight.application.processing.exceptions import EmbeddingError
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.exceptions import (
    InvalidGroundingError,
    QueryProfileUnavailableError,
    QueryProviderUnavailableError,
)
from document_insight.application.query.metrics import NullQueryMetrics, QueryMetrics
from document_insight.application.query.models import (
    AuthorizedRetrievalRequest,
    QueryCitation,
    QueryEntity,
    QueryResult,
    QueryStageTrace,
)
from document_insight.application.query.profile_resolver import QueryProfileResolver
from document_insight.infrastructure.active_profile.protocol import ActiveProfileRepository
from document_insight.infrastructure.department.protocol import DepartmentRepository
from document_insight.infrastructure.embedding.protocol import TextEmbedderFactory
from document_insight.infrastructure.generation.protocol import (
    GroundedAnswer,
    GroundedAnswerGeneratorFactory,
    GroundingPassage,
)
from document_insight.infrastructure.reranker.protocol import RerankerFactory, RerankInput
from document_insight.infrastructure.retrieval.protocol import (
    AuthorizedRetrievalRepository,
    EntityMatch,
    RetrievalScope,
    RetrievedChunk,
)


class QueryPreparationService:
    """Resolve immutable query configuration and authorization before retrieval starts."""

    def __init__(
        self,
        active_profiles: ActiveProfileRepository,
        profile_resolver: QueryProfileResolver,
        departments: DepartmentRepository,
        retrieval: AuthorizedRetrievalRepository,
        embedders: TextEmbedderFactory,
        rerankers: RerankerFactory,
        generators: GroundedAnswerGeneratorFactory,
        metrics: QueryMetrics | None = None,
        release_database_session: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._active_profiles = active_profiles
        self._profile_resolver = profile_resolver
        self._departments = departments
        self._retrieval = retrieval
        self._embedders = embedders
        self._rerankers = rerankers
        self._generators = generators
        self._metrics = metrics or NullQueryMetrics()
        # API reads release their connection before external provider waits. A later
        # retrieval starts a new transaction with the same verified actor context.
        # Optional because evaluation callers own their enclosing session lifecycle.
        self._release_database_session = release_database_session

    async def prepare(self, command: PrepareQueryCommand) -> AuthorizedRetrievalRequest:
        """Build an authorization-bounded request without reading chunks or invoking models."""
        return await self._prepare(command, None)

    async def _prepare(
        self, command: PrepareQueryCommand, query_profile_id: UUID | None
    ) -> AuthorizedRetrievalRequest:
        """Resolve one requested immutable profile under the actor's current scope."""
        if query_profile_id is None:
            query_profile_id = await self._active_profiles.get_query_profile_id("platform")
        if query_profile_id is None:
            raise QueryProfileUnavailableError
        profile = await self._profile_resolver.resolve(query_profile_id)
        authorized_departments = await self._authorized_departments(command)
        return AuthorizedRetrievalRequest(
            question=command.question,
            query_profile_id=profile.query_profile_id,
            lexical_profile_ids=profile.lexical_profile_ids,
            embedding_profile_ids=profile.embedding_profile_ids,
            tenant_id=command.actor.tenant_id,
            department_ids=authorized_departments,
            filter_text=command.filter_text,
            top_k=command.top_k,
        )

    async def _authorized_departments(self, command: PrepareQueryCommand) -> tuple[UUID, ...]:
        """Resolve tenant-admin scope or retain a non-admin's trusted token scope."""
        if command.actor.role is UserRole.TENANT_ADMIN:
            return await self._departments.list_all_ids(command.actor.tenant_id)
        return command.actor.department_ids

    async def query(self, command: PrepareQueryCommand) -> QueryResult:
        """Run all retrieval branches under one immutable profile and trusted scope."""
        return await self._query(command, None, None, None)

    async def query_for_evaluation(
        self,
        command: PrepareQueryCommand,
        query_profile_id: UUID,
        allowed_version_ids: tuple[UUID, ...],
        trace: QueryStageTrace,
    ) -> QueryResult:
        """Run a proposed profile only over explicitly selected authorized test versions."""
        if not allowed_version_ids:
            raise ValueError("Evaluation corpus must contain document versions")
        return await self._query(command, query_profile_id, allowed_version_ids, trace)

    async def _query(
        self,
        command: PrepareQueryCommand,
        query_profile_id: UUID | None,
        allowed_version_ids: tuple[UUID, ...] | None,
        trace: QueryStageTrace | None,
    ) -> QueryResult:
        """Execute the shared authorization-first production stages."""
        query_started_at = perf_counter()
        query_outcome = "error"
        try:
            prepared = await self._prepare(command, query_profile_id)
            profile = await self._profile_resolver.resolve(prepared.query_profile_id)
            scope = RetrievalScope(prepared.tenant_id, prepared.department_ids, allowed_version_ids)
            entity_matches = await self._entity_matches(
                scope, prepared.filter_text, profile.retrieval
            )
            lexical_query = " ".join(
                value for value in (prepared.question, prepared.filter_text) if value
            )
            lexical_started_at = perf_counter()
            try:
                lexical_results: list[tuple[RetrievedChunk, ...]] = []
                for cohort in profile.lexical_profile_ids:
                    candidates = await self._retrieval.lexical_search(
                        scope, cohort, lexical_query, profile.retrieval.lexical_candidate_limit
                    )
                    lexical_results.append(candidates)
                    if trace is not None:
                        trace.lexical_by_cohort[cohort] = candidates
            except Exception:
                self._observe_stage_duration("lexical_retrieval", "error", lexical_started_at)
                raise
            self._observe_stage_duration("lexical_retrieval", "success", lexical_started_at)
            lexical_lists = tuple(lexical_results)
            self._metrics.observe_candidate_count(
                "lexical_retrieval", sum(len(candidates) for candidates in lexical_lists)
            )
            vector_lists = await self._vector_lists(prepared.question, scope, profile, trace)
            self._metrics.observe_candidate_count(
                "vector_retrieval", sum(len(candidates) for candidates in vector_lists)
            )
            # Every remaining stage (fusion, reranking, evidence selection, generation)
            # works only on chunks already fetched into memory above; releasing the
            # database connection here keeps it from sitting idle through the
            # reranking and generation provider round trips.
            if self._release_database_session is not None:
                await self._release_database_session()
            fusion_started_at = perf_counter()
            try:
                fused = self._fuse(
                    (*lexical_lists, *vector_lists),
                    {match.document_version_id for match in entity_matches},
                    profile.retrieval.rrf_k,
                    profile.retrieval.entity_match_boost,
                )
            except Exception:
                self._observe_stage_duration("rrf_fusion", "error", fusion_started_at)
                raise
            self._observe_stage_duration("rrf_fusion", "success", fusion_started_at)
            self._metrics.observe_candidate_count("rrf_fusion", len(fused))
            if trace is not None:
                trace.fused = fused
            reranked = await self._rerank(
                prepared.question, fused, profile.retrieval.rerank_candidate_limit, profile
            )
            self._metrics.observe_candidate_count("reranking", len(reranked))
            if trace is not None:
                trace.reranked = tuple(chunk for chunk, _ in reranked)
            evidence_started_at = perf_counter()
            selected = reranked[: prepared.top_k]
            if not selected or selected[0][1] < profile.retrieval.insufficient_evidence_threshold:
                self._metrics.observe_candidate_count("evidence_selection", 0)
                self._observe_stage_duration(
                    "evidence_selection", "insufficient", evidence_started_at
                )
                query_outcome = "insufficient_evidence"
                return self._insufficient_evidence("below_evidence_threshold")
            citable = tuple(
                item for item in selected if item[1] >= profile.retrieval.min_citation_score
            )
            self._metrics.observe_candidate_count("evidence_selection", len(citable))
            if not citable:
                self._observe_stage_duration(
                    "evidence_selection", "insufficient", evidence_started_at
                )
                query_outcome = "insufficient_evidence"
                return self._insufficient_evidence("below_citation_threshold")
            self._observe_stage_duration("evidence_selection", "success", evidence_started_at)
            try:
                answer = await self._generate(prepared.question, citable, profile)
            except InvalidGroundingError:
                query_outcome = "insufficient_evidence"
                return self._insufficient_evidence("invalid_grounding")
            by_id = {chunk.chunk_id: (chunk, score) for chunk, score in citable}
            cited = tuple(
                by_id[chunk_id] for chunk_id in answer.cited_chunk_ids if chunk_id in by_id
            )
            if trace is not None:
                trace.cited_chunk_ids = tuple(chunk.chunk_id for chunk, _ in cited)
            if not cited:
                raise QueryProviderUnavailableError
            citations = tuple(
                QueryCitation(
                    chunk.document_id,
                    chunk.document_version_id,
                    chunk.chunk_id,
                    chunk.page_number,
                    chunk.text,
                    score,
                )
                for chunk, score in cited
            )
            cited_versions = {citation.document_version_id for citation in citations}
            entities = tuple(
                QueryEntity(match.document_version_id, match.display_value, match.label)
                for match in entity_matches
                if match.document_version_id in cited_versions
            )
            confidence = max(score for _, score in cited)
            self._metrics.observe_citation_count(len(citations))
            self._metrics.observe_evidence_confidence(confidence)
            query_outcome = "grounded"
            return QueryResult(answer.answer, confidence, citations, entities)
        finally:
            self._metrics.observe_query_duration(query_outcome, perf_counter() - query_started_at)

    def _insufficient_evidence(self, reason: str) -> QueryResult:
        """Return the single safe response for absent or ungroundable evidence."""
        self._metrics.increment_insufficient_evidence(reason)
        return QueryResult(
            "The information is not available in your authorized documents.", 0.0, (), ()
        )

    async def _entity_matches(
        self,
        scope: RetrievalScope,
        filter_text: str | None,
        retrieval: RetrievalConfiguration,
    ) -> tuple[EntityMatch, ...]:
        """Run the optional NER metadata lookup before passage retrieval, never as a filter."""
        if filter_text is None:
            return ()
        return await self._retrieval.find_entity_matches(
            scope, filter_text, retrieval.rerank_candidate_limit
        )

    async def _vector_lists(
        self,
        question: str,
        scope: RetrievalScope,
        profile: ResolvedQueryProfile,
        trace: QueryStageTrace | None = None,
    ) -> tuple[tuple[RetrievedChunk, ...], ...]:
        """Embed once per compatible cohort and never compare raw cross-cohort scores."""
        result: list[tuple[RetrievedChunk, ...]] = []
        for profile_id, configuration in profile.embedding_configurations:
            # Profile and lexical data are materialized. End the read transaction
            # before waiting for embeddings; the next SQL transaction rebinds RLS.
            if self._release_database_session is not None:
                await self._release_database_session()
            embedding_started_at = perf_counter()
            try:
                vector = (
                    await self._embedders.create(configuration).embed((question,), configuration)
                )[0]
            except (EmbeddingError, IndexError, ValueError) as error:
                self._observe_stage_duration("query_embedding", "error", embedding_started_at)
                raise QueryProviderUnavailableError from error
            except Exception:
                self._observe_stage_duration("query_embedding", "error", embedding_started_at)
                raise
            self._observe_stage_duration("query_embedding", "success", embedding_started_at)
            vector_retrieval_started_at = perf_counter()
            try:
                candidates = await self._retrieval.vector_search(
                    scope, profile_id, vector, profile.retrieval.vector_candidate_limit
                )
                result.append(candidates)
                if trace is not None:
                    trace.vector_by_cohort[profile_id] = candidates
            except Exception:
                self._observe_stage_duration(
                    "vector_retrieval", "error", vector_retrieval_started_at
                )
                raise
            self._observe_stage_duration("vector_retrieval", "success", vector_retrieval_started_at)
        return tuple(result)

    @staticmethod
    def _fuse(
        ranked_lists: tuple[tuple[RetrievedChunk, ...], ...],
        entity_version_ids: set[UUID],
        rrf_k: int,
        entity_boost: float,
    ) -> tuple[RetrievedChunk, ...]:
        """Fuse rank-only branch output with RRF and a bounded NER document boost."""
        scores: dict[UUID, float] = {}
        chunks: dict[UUID, RetrievedChunk] = {}
        for candidates in ranked_lists:
            for rank, candidate in enumerate(candidates, start=1):
                chunks[candidate.chunk_id] = candidate
                scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1 / (
                    rrf_k + rank
                )
        return tuple(
            chunks[chunk_id]
            for chunk_id in sorted(
                chunks,
                key=lambda chunk_id: (
                    -(
                        scores[chunk_id]
                        + (
                            entity_boost
                            if chunks[chunk_id].document_version_id in entity_version_ids
                            else 0.0
                        )
                    ),
                    str(chunk_id),
                ),
            )
        )

    async def _rerank(
        self,
        question: str,
        candidates: tuple[RetrievedChunk, ...],
        limit: int,
        profile: ResolvedQueryProfile,
    ) -> tuple[tuple[RetrievedChunk, float], ...]:
        """Rerank only authorized fused candidates, then apply the configured cap."""
        reranking_started_at = perf_counter()
        capped = candidates[:limit]
        if not capped:
            self._observe_stage_duration("reranking", "success", reranking_started_at)
            return ()
        try:
            scores = await self._rerankers.create(profile.reranking).rerank(
                question,
                tuple(RerankInput(candidate.chunk_id, candidate.text) for candidate in capped),
                profile.reranking,
            )
        except ValueError as error:
            self._observe_stage_duration("reranking", "error", reranking_started_at)
            raise QueryProviderUnavailableError from error
        except Exception:
            self._observe_stage_duration("reranking", "error", reranking_started_at)
            raise
        self._observe_stage_duration("reranking", "success", reranking_started_at)
        by_id = {score.chunk_id: score.score for score in scores}
        return tuple(
            sorted(
                ((candidate, by_id[candidate.chunk_id]) for candidate in capped),
                key=lambda item: (-item[1], str(item[0].chunk_id)),
            )
        )

    async def _generate(
        self,
        question: str,
        selected: tuple[tuple[RetrievedChunk, float], ...],
        profile: ResolvedQueryProfile,
    ) -> GroundedAnswer:
        """Send only selected authorized passages to the profile-selected generator."""
        generation_started_at = perf_counter()
        try:
            answer = await self._generators.create(profile.generation).generate(
                question,
                tuple(GroundingPassage(chunk.chunk_id, chunk.text) for chunk, _ in selected),
                profile.generation,
            )
        except InvalidGroundingError:
            self._observe_stage_duration("generation", "invalid_grounding", generation_started_at)
            raise
        except ValueError as error:
            self._observe_stage_duration("generation", "error", generation_started_at)
            raise QueryProviderUnavailableError from error
        except Exception:
            self._observe_stage_duration("generation", "error", generation_started_at)
            raise
        self._observe_stage_duration("generation", "success", generation_started_at)
        return answer

    def _observe_stage_duration(self, stage: str, outcome: str, started_at: float) -> None:
        """Record elapsed wall-clock time for one stage with a fixed label vocabulary."""
        self._metrics.observe_stage_duration(stage, outcome, perf_counter() - started_at)
