"""Mistral evidence-grounded answer generator."""

import json
import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from document_insight.application.configuration.models import GenerationConfiguration
from document_insight.application.query.exceptions import (
    InvalidGroundingError,
    QueryProviderUnavailableError,
)
from document_insight.infrastructure.generation.protocol import (
    GroundedAnswer,
    GroundedAnswerGenerator,
    GroundedAnswerGeneratorFactory,
    GroundingPassage,
)
from document_insight.infrastructure.mistral.agents import MistralStructuredAgentClient
from document_insight.infrastructure.observability.provider_metrics import ProviderCallMetrics

_INTERNAL_CITATION_MARKER = re.compile(
    r"\s*\(\s*chunk_id\s*:\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*\)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class _Response(BaseModel):
    """Strict output schema for a cited answer."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=16_000)
    cited_passage_indices: tuple[int, ...] = Field(min_length=1)


class MistralGroundedAnswerGenerator(GroundedAnswerGenerator):
    """Generate answers only from supplied, already-authorized passages."""

    def __init__(self, client: MistralStructuredAgentClient) -> None:
        self._client = client

    async def generate(
        self,
        question: str,
        passages: tuple[GroundingPassage, ...],
        configuration: GenerationConfiguration,
    ) -> GroundedAnswer:
        """Generate a cited answer and reject references outside the passage set."""
        metrics = ProviderCallMetrics("mistral", "generation")
        input_text = json.dumps(
            {
                "question": question,
                "passages": [
                    {"position": index, "text": item.text}
                    for index, item in enumerate(passages, start=1)
                ],
            }
        )
        for attempt in range(2):
            try:
                response = await self._client.complete(
                    name="Evidence-grounded answer generator",
                    instructions=(
                        configuration.system_prompt
                        if attempt == 0
                        else configuration.system_prompt + " " + configuration.correction_prompt
                    ),
                    input_text=input_text,
                    model_name=configuration.model,
                    output_type=_Response,
                    temperature=configuration.temperature,
                    max_output_tokens=configuration.max_output_tokens,
                )
            except QueryProviderUnavailableError:
                metrics.retryable_failure("provider_unavailable")
                raise
            cited_indices = response.cited_passage_indices
            if all(1 <= index <= len(passages) for index in cited_indices):
                break
            logger.warning(
                "Mistral returned invalid citation positions; requesting one correction",
                extra={"attempt": attempt + 1, "passage_count": len(passages)},
            )
        else:
            metrics.failure("invalid_grounding")
            raise InvalidGroundingError
        cited_chunk_ids = tuple(
            dict.fromkeys(passages[index - 1].chunk_id for index in cited_indices)
        )
        metrics.success()
        return GroundedAnswer(
            _INTERNAL_CITATION_MARKER.sub("", response.answer).strip(),
            cited_chunk_ids,
        )


class MistralGroundedAnswerGeneratorFactory(GroundedAnswerGeneratorFactory):
    """Create the explicit Mistral generation adapter."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = MistralStructuredAgentClient(base_url, api_key)

    def create(self, configuration: GenerationConfiguration) -> GroundedAnswerGenerator:
        """Return Mistral only for profiles that explicitly select it."""
        if configuration.provider != "mistral":
            raise ValueError(f"Unsupported generation provider: {configuration.provider}")
        return MistralGroundedAnswerGenerator(self._client)
