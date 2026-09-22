"""Tests for safe presentation of Mistral grounded answers."""

import asyncio
from uuid import uuid4

import pytest

from document_insight.application.configuration.models import GenerationConfiguration
from document_insight.application.query.exceptions import InvalidGroundingError
from document_insight.infrastructure.generation.mistral import (
    MistralGroundedAnswerGenerator,
    _Response,
)
from document_insight.infrastructure.generation.protocol import GroundingPassage


class _FakeAgentClient:
    def __init__(self, *responses: _Response) -> None:
        self._responses = list(responses)

    async def complete(self, **_: object) -> _Response:
        return self._responses.pop(0)


def test_generator_removes_internal_chunk_identifiers_from_answer_text() -> None:
    """Citations belong in the structured field and source UI, not answer prose."""
    chunk_id = uuid4()
    generator = MistralGroundedAnswerGenerator(
        _FakeAgentClient(
            _Response(
                answer=f"Evidence supports this (chunk_id: {chunk_id}).", cited_passage_indices=(1,)
            )
        )  # type: ignore[arg-type]
    )
    configuration = GenerationConfiguration(
        provider="mistral",
        model="ministral-3b-2512",
        configuration_revision="ministral-3b-2512",
        prompt_revision="grounded-answer-v3",
        response_schema_revision="grounded-answer-indices-v1",
        temperature=0.0,
        max_output_tokens=1024,
    )

    result = asyncio.run(
        generator.generate(
            "What does the evidence say?",
            (GroundingPassage(chunk_id, "Evidence supports this."),),
            configuration,
        )
    )

    assert result.answer == "Evidence supports this."
    assert result.cited_chunk_ids == (chunk_id,)


def test_generator_retries_invalid_citation_positions_once() -> None:
    """A transient bad position receives one constrained correction attempt."""
    first_id, second_id = uuid4(), uuid4()
    generator = MistralGroundedAnswerGenerator(
        _FakeAgentClient(
            _Response(answer="Evidence supports this.", cited_passage_indices=(99,)),
            _Response(answer="Evidence supports this.", cited_passage_indices=(2,)),
        )  # type: ignore[arg-type]
    )
    configuration = GenerationConfiguration(
        provider="mistral",
        model="ministral-3b-2512",
        configuration_revision="ministral-3b-2512",
        prompt_revision="grounded-answer-v3",
        response_schema_revision="grounded-answer-indices-v1",
        temperature=0.0,
        max_output_tokens=1024,
    )

    result = asyncio.run(
        generator.generate(
            "What does the evidence say?",
            (GroundingPassage(first_id, "First."), GroundingPassage(second_id, "Second.")),
            configuration,
        )
    )

    assert result.cited_chunk_ids == (second_id,)


def test_generator_rejects_an_answer_without_valid_citations() -> None:
    """The generator never substitutes all passages for an invalid citation."""
    chunk_id = uuid4()
    generator = MistralGroundedAnswerGenerator(
        _FakeAgentClient(
            _Response(answer="Evidence supports this.", cited_passage_indices=(99,)),
            _Response(answer="Evidence supports this.", cited_passage_indices=(0,)),
        )  # type: ignore[arg-type]
    )
    configuration = GenerationConfiguration(
        provider="mistral",
        model="ministral-3b-2512",
        configuration_revision="1",
        prompt_revision="1",
        response_schema_revision="1",
        temperature=0.0,
        max_output_tokens=1024,
    )

    with pytest.raises(InvalidGroundingError):
        asyncio.run(
            generator.generate(
                "What does the evidence say?",
                (GroundingPassage(chunk_id, "Evidence."),),
                configuration,
            )
        )
