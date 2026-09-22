"""Tests for the Mistral ordered-score reranker contract."""

import asyncio
from uuid import uuid4

from document_insight.application.configuration.models import RerankingConfiguration
from document_insight.infrastructure.reranker.mistral import MistralReranker, _Response
from document_insight.infrastructure.reranker.protocol import RerankInput


class _FakeAgentClient:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    async def complete(self, **kwargs: object) -> _Response:
        self.instructions.append(str(kwargs["instructions"]))
        return _Response(scores=(0.9, 0.2))


def test_reranker_attaches_ordered_scores_to_authorized_chunk_ids() -> None:
    """The model never needs to reproduce opaque chunk identifiers."""
    first_id, second_id = uuid4(), uuid4()
    client = _FakeAgentClient()
    reranker = MistralReranker(client)  # type: ignore[arg-type]
    configuration = RerankingConfiguration(
        provider="mistral",
        model="ministral-3b-2512",
        configuration_revision="ministral-3b-2512",
        prompt_revision="llm-rerank-v2",
        system_prompt="Profile reranking instructions.",
        response_schema_revision="rerank-scores-v2",
        temperature=0.0,
        max_output_tokens=2048,
    )

    scores = asyncio.run(
        reranker.rerank(
            "Which is more relevant?",
            (RerankInput(first_id, "First passage"), RerankInput(second_id, "Second passage")),
            configuration,
        )
    )

    assert tuple((score.chunk_id, score.score) for score in scores) == (
        (first_id, 0.9),
        (second_id, 0.2),
    )
    assert client.instructions == ["Profile reranking instructions."]
