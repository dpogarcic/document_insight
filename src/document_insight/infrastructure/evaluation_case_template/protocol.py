"""Read contract for reusable evaluation case templates."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EvaluationCaseTemplate:
    """Corpus-independent scenario for drafting a labelled evaluation case."""

    template_id: UUID
    key: str
    title: str
    question: str
    answerability: str
    review_rubric: str
    scenario_tag: str


class EvaluationCaseTemplateRepository(Protocol):
    """List seeded templates in their suggested display order."""

    async def list_all(self) -> tuple[EvaluationCaseTemplate, ...]: ...
