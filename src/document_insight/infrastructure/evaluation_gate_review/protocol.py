"""Repository contract for operator evaluation decisions."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GateReview:
    """One operator decision against an exact completed run."""

    review_id: UUID
    run_id: UUID
    operator_id: UUID
    decision: str
    reason: str
    reviewed_run_id: UUID
    created_at: str
    threshold_revision: str = "1"


class EvaluationGateReviewRepository(Protocol):
    """Own append-only gate decisions."""

    async def create(self, review: GateReview) -> UUID: ...
    async def get_for_run(self, run_id: UUID) -> GateReview | None: ...
    async def list_reviews(self, operator_id: UUID | None = None) -> tuple[GateReview, ...]: ...
