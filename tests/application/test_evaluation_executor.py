"""Evaluation uses the real query contract and rejects other tenant identities."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.evaluation.executor import QueryEvaluationExecutor
from document_insight.application.query.models import QueryCitation, QueryResult, QueryStageTrace
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
)
from document_insight.infrastructure.retrieval.protocol import RetrievedChunk


@dataclass
class Actors:
    actor: AuthorizationContext

    async def load(self, user_id: UUID) -> AuthorizationContext:
        assert user_id == self.actor.user_id
        return self.actor


@dataclass
class Query:
    chunk: RetrievedChunk
    seen_versions: tuple[UUID, ...] = ()

    async def query_for_evaluation(
        self,
        command: object,
        query_profile_id: UUID,
        allowed_version_ids: tuple[UUID, ...],
        trace: QueryStageTrace,
    ) -> QueryResult:
        self.seen_versions = allowed_version_ids
        trace.lexical_by_cohort[uuid4()] = (self.chunk,)
        trace.vector_by_cohort[uuid4()] = (self.chunk,)
        trace.fused = (self.chunk,)
        trace.reranked = (self.chunk,)
        trace.cited_chunk_ids = (self.chunk.chunk_id,)
        return QueryResult(
            "Annual renewal",
            0.9,
            (
                QueryCitation(
                    self.chunk.document_id,
                    self.chunk.document_version_id,
                    self.chunk.chunk_id,
                    self.chunk.page_number,
                    self.chunk.text,
                    0.9,
                ),
            ),
            (),
        )


@pytest.mark.anyio
async def test_executor_maps_ranked_chunks_to_stable_source_spans() -> None:
    tenant_id, source_version, indexed_version, profile_id = (uuid4() for _ in range(4))
    actor = AuthorizationContext(uuid4(), tenant_id, (uuid4(),), UserRole.VIEWER)
    chunk = RetrievedChunk(
        uuid4(),
        uuid4(),
        indexed_version,
        "Contract",
        "Annual renewal",
        2,
        0.8,
        10,
        30,
    )
    query = Query(chunk)
    case = EvaluationTestCase(
        uuid4(),
        uuid4(),
        "Renewal?",
        None,
        actor.user_id,
        Answerability.ANSWERABLE,
        None,
        None,
        {},
        (),
        0,
    )
    executor = QueryEvaluationExecutor(query, Actors(actor), tenant_id)  # type: ignore[arg-type]
    result = await executor.execute(
        case, profile_id, (indexed_version,), {indexed_version: source_version}, top_k=5
    )
    assert query.seen_versions == (indexed_version,)
    assert result.lexical_ranked_ids == (f"{source_version}@2:10:30",)
    assert result.final_citations[0]["source_anchor"] == f"{source_version}@2:10:30"
    assert result.answerability_outcome == "answered"


@pytest.mark.anyio
async def test_executor_rejects_identity_outside_evaluation_tenant() -> None:
    actor = AuthorizationContext(uuid4(), uuid4(), (uuid4(),), UserRole.VIEWER)
    chunk = RetrievedChunk(uuid4(), uuid4(), uuid4(), "", "x", 1, 0.8, 0, 1)
    executor = QueryEvaluationExecutor(Query(chunk), Actors(actor), uuid4())  # type: ignore[arg-type]
    case = EvaluationTestCase(
        uuid4(),
        uuid4(),
        "Question",
        None,
        actor.user_id,
        Answerability.ANSWERABLE,
        None,
        None,
        {},
        (),
        0,
    )
    with pytest.raises(ValueError, match="outside"):
        await executor.execute(
            case,
            uuid4(),
            (chunk.document_version_id,),
            {chunk.document_version_id: chunk.document_version_id},
            top_k=1,
        )
