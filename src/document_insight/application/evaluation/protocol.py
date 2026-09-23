"""Protocol and result types for the evaluation runner."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.application.evaluation.commands import LaunchEvaluationRunCommand
from document_insight.application.evaluation.models import TestCaseResult


@dataclass(frozen=True, slots=True)
class EvaluationRunResult:
    """Result from completing an evaluation run."""

    run_id: UUID
    status: str
    case_results: tuple[TestCaseResult, ...]
    aggregates: tuple[dict[str, object], ...]


class EvaluationRunnerProtocol(Protocol):
    """Protocol for evaluation runners."""

    async def run(
        self,
        command: LaunchEvaluationRunCommand,
    ) -> EvaluationRunResult:
        """Execute an evaluation run."""
        ...
