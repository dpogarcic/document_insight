"""Repository contract for immutable evaluation suite revisions."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from document_insight.infrastructure.evaluation_test_case.protocol import (
    EvaluationTestCase,
)


@dataclass(frozen=True, slots=True)
class EvaluationSuiteRevision:
    """A named revision and its approved, version-scoped test corpus."""

    revision_id: UUID
    suite_name: str
    revision_number: int
    created_by: UUID
    created_at: str
    test_cases: tuple[EvaluationTestCase, ...]
    evaluation_tenant_id: UUID | None = None
    corpus_version_ids: tuple[UUID, ...] = ()
    dataset_fingerprint: str = ""


class EvaluationSuiteRepository(Protocol):
    """Own only suite-revision rows."""

    async def get_revision(self, revision_id: UUID) -> EvaluationSuiteRevision | None: ...
    async def list_revisions(
        self, suite_name: str, tenant_id: UUID | None = None
    ) -> tuple[EvaluationSuiteRevision, ...]: ...
    async def create_revision(
        self,
        suite_name: str,
        created_by: UUID,
        evaluation_tenant_id: UUID,
        corpus_version_ids: tuple[UUID, ...],
        dataset_fingerprint: str,
    ) -> UUID: ...
    async def get_active_revision(
        self, suite_name: str, tenant_id: UUID
    ) -> EvaluationSuiteRevision | None: ...
    async def set_active_revision(
        self, revision_id: UUID, suite_name: str, tenant_id: UUID
    ) -> None: ...
