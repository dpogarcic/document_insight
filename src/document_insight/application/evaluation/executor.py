"""Execute one labelled case through the real authorization-first query pipeline."""

from time import perf_counter
from typing import Protocol
from uuid import UUID

from document_insight.application.auth.models import AuthorizationContext
from document_insight.application.evaluation.models import TestCaseResult
from document_insight.application.evaluation.scoring import SourceSpan
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.models import QueryStageTrace
from document_insight.application.query.service import QueryPreparationService
from document_insight.infrastructure.evaluation_test_case.protocol import EvaluationTestCase
from document_insight.infrastructure.retrieval.protocol import RetrievedChunk


class EvaluationActorLoader(Protocol):
    """Resolve a current identity before retrieving passages."""

    async def load(self, user_id: UUID) -> AuthorizationContext:
        """Return the identity's current tenant, role, and department memberships."""


class QueryEvaluationExecutor:
    """Capture actual cohort rankings, citations, and answer outcome for one case."""

    def __init__(
        self,
        query: QueryPreparationService,
        actors: EvaluationActorLoader,
        tenant_id: UUID,
    ) -> None:
        self._query = query
        self._actors = actors
        self._tenant_id = tenant_id

    async def execute(
        self,
        case: EvaluationTestCase,
        query_profile_id: UUID,
        allowed_version_ids: tuple[UUID, ...],
        source_versions: dict[UUID, UUID],
        *,
        top_k: int,
    ) -> TestCaseResult:
        """Run one case only over the approved corpus and current identity scope."""
        actor = await self._actors.load(case.authorized_identity_id)
        if actor.tenant_id != self._tenant_id:
            raise ValueError("Evaluation identity is outside the selected tenant")
        if any(version not in source_versions for version in allowed_version_ids):
            raise ValueError("Evaluation corpus is missing a source-version mapping")
        trace = QueryStageTrace()
        started = perf_counter()
        result = await self._query.query_for_evaluation(
            PrepareQueryCommand(case.question, case.filter_text, top_k, actor),
            query_profile_id,
            allowed_version_ids,
            trace,
        )
        chunks = {item.chunk_id: item for item in trace.fused}
        citations: list[dict[str, object]] = []
        for citation in result.citations:
            chunk = chunks[citation.chunk_id]
            citations.append(
                {
                    "source_anchor": self._anchor(chunk, source_versions),
                    "chunk_id": str(chunk.chunk_id),
                    "score": citation.relevance_score,
                }
            )
        return TestCaseResult(
            case_id=case.case_id,
            status="completed",
            lexical_ranked_ids=self._flatten(trace.lexical_by_cohort, source_versions),
            vector_cohort_ranked_ids={
                str(cohort): tuple(self._anchor(chunk, source_versions) for chunk in chunks)
                for cohort, chunks in trace.vector_by_cohort.items()
            },
            vector_combined_ranked_ids=self._flatten(trace.vector_by_cohort, source_versions),
            fused_ranked_ids=tuple(self._anchor(chunk, source_versions) for chunk in trace.fused),
            reranked_ranked_ids=tuple(
                self._anchor(chunk, source_versions) for chunk in trace.reranked
            ),
            final_citations=tuple(citations),
            answer_text=result.answer,
            answerability_outcome="answered" if result.citations else "refused",
            provider_errors=(),
            stage_latencies_ms={"total": (perf_counter() - started) * 1000},
            lexical_cohort_ranked_ids={
                str(cohort): tuple(self._anchor(chunk, source_versions) for chunk in chunks)
                for cohort, chunks in trace.lexical_by_cohort.items()
            },
        )

    @staticmethod
    def _anchor(chunk: RetrievedChunk, source_versions: dict[UUID, UUID]) -> str:
        """Map a derived chunk back to its immutable original source span."""
        if chunk.page_number is None or chunk.end_offset <= chunk.start_offset:
            raise ValueError("Retrieved passage has no usable source offsets")
        return SourceSpan(
            source_versions[chunk.document_version_id],
            chunk.page_number,
            chunk.start_offset,
            chunk.end_offset,
        ).encode()

    @classmethod
    def _flatten(
        cls,
        by_cohort: dict[UUID, tuple[RetrievedChunk, ...]],
        source_versions: dict[UUID, UUID],
    ) -> tuple[str, ...]:
        """Keep first-seen rank order when summarizing multiple cohort lists."""
        return tuple(
            dict.fromkeys(
                cls._anchor(chunk, source_versions)
                for candidates in by_cohort.values()
                for chunk in candidates
            )
        )
