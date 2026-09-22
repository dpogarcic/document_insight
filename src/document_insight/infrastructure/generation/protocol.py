"""Grounded answer generation provider boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.configuration.models import GenerationConfiguration


@dataclass(frozen=True, slots=True)
class GroundingPassage:
    chunk_id: UUID
    text: str


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    cited_chunk_ids: tuple[UUID, ...]


class GroundedAnswerGenerator(Protocol):
    async def generate(
        self,
        question: str,
        passages: tuple[GroundingPassage, ...],
        configuration: GenerationConfiguration,
    ) -> GroundedAnswer: ...


class GroundedAnswerGeneratorFactory(Protocol):
    def create(self, configuration: GenerationConfiguration) -> GroundedAnswerGenerator: ...
