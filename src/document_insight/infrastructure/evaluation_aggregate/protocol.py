"""Repository contract for aggregate evaluation measurements."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AggregateMeasurement:
    """One micro-aggregate with auditable counts and definition."""

    measurement_id: UUID
    run_id: UUID
    metric_name: str
    metric_value: float
    case_count: int
    numerator: int | None
    denominator: int | None
    definition: str
    variant: str = "candidate"
    stage: str = "overall"
    k: int | None = None
    cohort_id: UUID | None = None


class EvaluationAggregateRepository(Protocol):
    """Own one measurement row at a time."""

    async def add(self, measurement: AggregateMeasurement) -> None: ...
    async def list_for_run(self, run_id: UUID) -> tuple[AggregateMeasurement, ...]: ...
