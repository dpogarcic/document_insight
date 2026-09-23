"""Application errors for evaluation operations."""

from uuid import UUID


class EvaluationError(Exception):
    """Base exception for evaluation operations."""

    pass


class GateReviewError(EvaluationError):
    """Error during gate review operations."""

    pass


class ProfileMismatchError(EvaluationError):
    """Error when profile configuration doesn't match expectations."""

    pass


class SuiteRevisionError(EvaluationError):
    """Error during suite revision operations."""

    pass


class RunNotFoundError(EvaluationError):
    """Raised when an evaluation run cannot be found."""

    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        super().__init__(f"Evaluation run not found: {run_id}")


class CaseNotFoundError(EvaluationError):
    """Raised when an evaluation case cannot be found."""

    def __init__(self, case_id: UUID) -> None:
        self.case_id = case_id
        super().__init__(f"Evaluation case not found: {case_id}")


class InvalidRunStateError(EvaluationError):
    """Raised when attempting an operation on a run in an invalid state."""

    pass
