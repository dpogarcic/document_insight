"""Repository contract for labelled evaluation cases."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class Answerability(StrEnum):
    ANSWERABLE = "answerable"
    UNANSWERABLE = "unanswerable"


@dataclass(frozen=True, slots=True)
class EvaluationTestCase:
    """One approved question, identity, and source-span judgement set."""

    case_id: UUID
    suite_revision_id: UUID
    question: str
    filter_text: str | None
    authorized_identity_id: UUID
    answerability: Answerability
    expected_facts: dict[str, object] | None
    review_rubric: str | None
    tags: dict[str, str]
    relevant_passage_ids: tuple[str, ...]
    sort_order: int
    relevance_complete: bool = False


class EvaluationTestCaseRepository(Protocol):
    """Own the immutable labels within one suite revision."""

    async def create_many(
        self, revision_id: UUID, cases: tuple[EvaluationTestCase, ...]
    ) -> None: ...
    async def list_for_revision(self, revision_id: UUID) -> tuple[EvaluationTestCase, ...]: ...
