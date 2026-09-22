"""Reranking provider boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.configuration.models import RerankingConfiguration


@dataclass(frozen=True, slots=True)
class RerankInput:
    chunk_id: UUID
    text: str


@dataclass(frozen=True, slots=True)
class RerankScore:
    chunk_id: UUID
    score: float


class Reranker(Protocol):
    async def rerank(self, question: str, candidates: tuple[RerankInput, ...], configuration: RerankingConfiguration) -> tuple[RerankScore, ...]: ...


class RerankerFactory(Protocol):
    def create(self, configuration: RerankingConfiguration) -> Reranker: ...
