"""Application service for managing evaluation suites and runs."""

import json
from dataclasses import dataclass, replace
from datetime import UTC
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from document_insight.application.evaluation.commands import (
    EvaluationRunRecord,
    LaunchEvaluationRunCommand,
)
from document_insight.application.evaluation.exceptions import (
    EvaluationError,
    GateReviewError,
)
from document_insight.application.evaluation.models import EvaluationCorpusManifest
from document_insight.application.evaluation.scoring import SourceSpan
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfileRepository
from document_insight.infrastructure.configuration_snapshot.protocol import (
    ConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.transaction import TransactionManager
from document_insight.infrastructure.evaluation_aggregate.protocol import (
    AggregateMeasurement,
    EvaluationAggregateRepository,
)
from document_insight.infrastructure.evaluation_case_result.protocol import (
    CaseResultStatus,
    EvaluationCaseResult,
    EvaluationCaseResultRepository,
)
from document_insight.infrastructure.evaluation_gate_review.protocol import (
    EvaluationGateReviewRepository,
    GateReview,
)
from document_insight.infrastructure.evaluation_run.protocol import (
    EvaluationRun,
    EvaluationRunRepository,
    RunStatus,
)
from document_insight.infrastructure.evaluation_suite.protocol import (
    EvaluationSuiteRepository,
    EvaluationSuiteRevision,
)
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
    EvaluationTestCaseRepository,
)
from document_insight.infrastructure.ingestion_profile.protocol import IngestionProfileRepository
from document_insight.infrastructure.query_profile.protocol import QueryProfileRepository

_CASE_KEYS = frozenset(
    {
        "question",
        "authorized_identity_id",
        "answerability",
        "relevance_complete",
        "relevant_passage_ids",
        "filter_text",
        "expected_facts",
        "review_rubric",
        "tags",
    }
)


@dataclass(frozen=True, slots=True)
class EvaluationService:
    """Manage evaluation suites, runs, and gate reviews."""

    suite_repo: EvaluationSuiteRepository
    run_repo: EvaluationRunRepository
    transactions: TransactionManager
    case_repo: EvaluationCaseResultRepository
    aggregate_repo: EvaluationAggregateRepository
    review_repo: EvaluationGateReviewRepository
    test_case_repo: EvaluationTestCaseRepository
    query_profiles: QueryProfileRepository | None = None
    capability_profiles: CapabilityProfileRepository | None = None
    snapshots: ConfigurationSnapshotRepository | None = None
    ingestion_profiles: IngestionProfileRepository | None = None

    async def create_suite_revision(
        self,
        suite_name: str,
        created_by: UUID,
        test_cases: tuple[dict[str, Any], ...],
        evaluation_tenant_id: UUID,
        corpus_version_ids: tuple[UUID, ...],
    ) -> UUID:
        """Create a new immutable evaluation suite revision."""
        if not suite_name.strip() or len(suite_name) > 200:
            raise EvaluationError("Suite name must be 1-200 characters")

        if not test_cases:
            raise EvaluationError("An evaluation suite needs at least one case")
        if not corpus_version_ids or len(set(corpus_version_ids)) != len(corpus_version_ids):
            raise EvaluationError("The evaluation corpus needs distinct document versions")
        validated_cases = tuple(
            self._validate_test_case(tc, index, corpus_version_ids)
            for index, tc in enumerate(test_cases)
        )
        canonical = json.dumps(
            {
                "suite_name": suite_name.strip(),
                "tenant_id": str(evaluation_tenant_id),
                "corpus_version_ids": [str(value) for value in corpus_version_ids],
                "test_cases": test_cases,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = sha256(canonical.encode()).hexdigest()

        async with self.transactions.begin():
            revision_id = await self.suite_repo.create_revision(
                suite_name.strip(),
                created_by,
                evaluation_tenant_id,
                corpus_version_ids,
                fingerprint,
            )
            await self.test_case_repo.create_many(revision_id, validated_cases)
        return revision_id

    async def list_suites(
        self, suite_name: str, tenant_id: UUID | None = None
    ) -> tuple[EvaluationSuiteRevision, ...]:
        """List all revisions of a suite."""
        async with self.transactions.begin():
            revisions = await self.suite_repo.list_revisions(suite_name, tenant_id)
            return tuple([await self._full_suite(item) for item in revisions])

    async def get_suite_revision(self, revision_id: UUID) -> EvaluationSuiteRevision | None:
        """Get a specific suite revision."""
        async with self.transactions.begin():
            revision = await self.suite_repo.get_revision(revision_id)
            return None if revision is None else await self._full_suite(revision)

    async def _full_suite(self, revision: EvaluationSuiteRevision) -> EvaluationSuiteRevision:
        return replace(
            revision, test_cases=await self.test_case_repo.list_for_revision(revision.revision_id)
        )

    async def set_active_suite(self, revision_id: UUID, suite_name: str, tenant_id: UUID) -> None:
        """Set the active revision for a suite."""
        async with self.transactions.begin():
            await self.suite_repo.set_active_revision(revision_id, suite_name, tenant_id)

    async def launch_run(self, command: LaunchEvaluationRunCommand) -> UUID:
        """Persist an immutable, validated run before queue publication."""
        if command.evaluation_mode not in ("query", "ingestion"):
            raise EvaluationError("Evaluation mode must be query or ingestion")
        if len(command.baseline_profile_ids) != 1 or len(command.candidate_profile_ids) != 1:
            raise EvaluationError("Select exactly one baseline and candidate query policy")
        if (
            command.evaluation_mode == "query"
            and command.baseline_profile_ids == command.candidate_profile_ids
        ):
            raise EvaluationError("Candidate must differ from the active baseline")
        if not command.k_values or any(k < 1 or k > 100 for k in command.k_values):
            raise EvaluationError("K values must be between 1 and 100")
        if len(set(command.k_values)) != len(command.k_values):
            raise EvaluationError("K values must be distinct")
        suite = await self.get_suite_revision(command.suite_revision_id)
        if suite is None or suite.evaluation_tenant_id is None:
            raise EvaluationError("The approved evaluation suite is unavailable")
        try:
            manifest = EvaluationCorpusManifest.from_json(command.corpus_manifest)
        except (ValueError, TypeError) as error:
            raise EvaluationError("Evaluation corpus manifest is invalid") from error
        source_ids = set(suite.corpus_version_ids)
        if (
            manifest.suite_fingerprint != suite.dataset_fingerprint
            or manifest.baseline_query_profile_id != command.baseline_profile_ids[0]
            or manifest.candidate_query_profile_id != command.candidate_profile_ids[0]
            or set(manifest.baseline.version_ids) != source_ids
            or any(key != value for key, value in manifest.baseline.source_versions.items())
        ):
            raise EvaluationError("Run corpus does not match the immutable suite")
        if command.evaluation_mode == "query":
            if set(manifest.candidate.version_ids) != source_ids or any(
                key != value for key, value in manifest.candidate.source_versions.items()
            ):
                raise EvaluationError("Query evaluation must reuse the exact approved corpus")
        elif (
            manifest.baseline_ingestion_profile_id is None
            or manifest.candidate_ingestion_profile_id is None
            or manifest.baseline_ingestion_profile_id == manifest.candidate_ingestion_profile_id
            or set(manifest.candidate.source_versions.values()) != source_ids
            or set(manifest.candidate.source_versions) != set(manifest.candidate.version_ids)
            or len(manifest.candidate.version_ids) != len(source_ids)
            or set(manifest.candidate.version_ids) & source_ids
            or manifest.baseline_query_profile_id != manifest.candidate_query_profile_id
        ):
            raise EvaluationError("Ingestion evaluation needs one distinct indexed copy per source")
        run_id = uuid4()

        async with self.transactions.begin():
            config_fingerprints = await self._build_config_fingerprints(
                command.baseline_profile_ids,
                command.candidate_profile_ids,
            )
            read_cohorts = await self._read_cohorts(
                command.baseline_profile_ids[0], command.candidate_profile_ids[0]
            )
            if command.evaluation_mode == "ingestion":
                assert manifest.baseline_ingestion_profile_id is not None
                assert manifest.candidate_ingestion_profile_id is not None
                await self._require_ingestion_cohorts(manifest)
                config_fingerprints.update(
                    {
                        "baseline_ingestion": await self._ingestion_fingerprint(
                            manifest.baseline_ingestion_profile_id
                        ),
                        "candidate_ingestion": await self._ingestion_fingerprint(
                            manifest.candidate_ingestion_profile_id
                        ),
                    }
                )

        run = EvaluationRun(
            run_id=run_id,
            suite_revision_id=command.suite_revision_id,
            corpus_manifest={
                **manifest.to_json(),
                "evaluation_tenant_id": str(suite.evaluation_tenant_id),
            },
            baseline_profile_ids=command.baseline_profile_ids,
            candidate_profile_ids=command.candidate_profile_ids,
            config_fingerprints=config_fingerprints,
            read_cohorts=read_cohorts,
            candidate_component_profiles=command.candidate_component_profiles,
            evaluator_version=command.evaluator_version,
            k_values=command.k_values,
            requester_id=command.requester_id,
            evaluation_mode=command.evaluation_mode,
            status=RunStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_message=None,
            comparison_valid=True,
            per_case_results=(),
            aggregate_measurements=(),
        )

        async with self.transactions.begin():
            await self.run_repo.create_run(run)

        return run_id

    async def update_run_status(
        self,
        run_id: UUID,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a run."""
        run_status = RunStatus(status)
        async with self.transactions.begin():
            await self.run_repo.update_run_status(
                run_id, run_status, started_at, completed_at, error_message
            )

    async def claim_run(self, run_id: UUID) -> bool:
        """Claim a durable run exactly once across duplicate worker deliveries."""
        async with self.transactions.begin():
            return await self.run_repo.claim_pending(run_id, _now_iso())

    async def list_pending_ids(self) -> tuple[UUID, ...]:
        """List unclaimed runs so a reconciler can repair lost queue delivery."""
        async with self.transactions.begin():
            return await self.run_repo.list_pending_ids()

    async def mark_enqueued(self, run_id: UUID) -> None:
        """Record that Redis accepted the durable run identifier."""
        async with self.transactions.begin():
            await self.run_repo.mark_enqueued(run_id, _now_iso())

    async def touch_heartbeat(self, run_id: UUID) -> None:
        """Advance the durable progress timestamp after each case variant."""
        async with self.transactions.begin():
            await self.run_repo.touch_heartbeat(run_id, _now_iso())

    async def fail_stale_running(self, stale_before: str) -> tuple[UUID, ...]:
        """Mark abandoned workers failed without exposing case or provider content."""
        async with self.transactions.begin():
            return await self.run_repo.fail_stale_running(stale_before, _now_iso())

    async def add_case_result(
        self,
        run_id: UUID,
        case_id: UUID,
        status: str,
        lexical_ranked_ids: tuple[str, ...],
        vector_cohort_ranked_ids: dict[str, tuple[str, ...]],
        vector_combined_ranked_ids: tuple[str, ...],
        fused_ranked_ids: tuple[str, ...],
        reranked_ranked_ids: tuple[str, ...],
        final_citations: tuple[dict[str, object], ...],
        answer_text: str | None,
        answerability_outcome: str | None,
        provider_errors: tuple[str, ...],
        stage_latencies_ms: dict[str, float],
        started_at: str,
        completed_at: str | None,
        variant: str = "candidate",
        measurements: tuple[dict[str, object], ...] = (),
        lexical_cohort_ranked_ids: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        """Add a case result to a run."""
        result = EvaluationCaseResult(
            result_id=uuid4(),
            run_id=run_id,
            case_id=case_id,
            status=CaseResultStatus(status),
            lexical_ranked_ids=lexical_ranked_ids,
            vector_cohort_ranked_ids=vector_cohort_ranked_ids,
            vector_combined_ranked_ids=vector_combined_ranked_ids,
            fused_ranked_ids=fused_ranked_ids,
            reranked_ranked_ids=reranked_ranked_ids,
            final_citations=final_citations,
            answer_text=answer_text,
            answerability_outcome=answerability_outcome,
            provider_errors=provider_errors,
            stage_latencies_ms=stage_latencies_ms,
            started_at=started_at,
            completed_at=completed_at,
            variant=variant,
            measurements=measurements,
            lexical_cohort_ranked_ids=lexical_cohort_ranked_ids,
        )
        async with self.transactions.begin():
            await self.case_repo.add(result)

    async def add_aggregate(self, run_id: UUID, measurement: AggregateMeasurement) -> None:
        """Add an aggregate measurement to a run."""
        async with self.transactions.begin():
            await self.aggregate_repo.add(measurement)

    async def get_run(self, run_id: UUID) -> EvaluationRun | None:
        """Get a run by ID."""
        async with self.transactions.begin():
            run = await self.run_repo.get_run(run_id)
            return None if run is None else await self._full_run(run)

    async def _full_run(self, run: EvaluationRun) -> EvaluationRun:
        return replace(
            run,
            per_case_results=await self.case_repo.list_for_run(run.run_id),
            aggregate_measurements=await self.aggregate_repo.list_for_run(run.run_id),
        )

    async def list_runs(
        self,
        suite_revision_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[EvaluationRun, ...]:
        """List runs with optional filters."""
        run_status = RunStatus(status) if status else None
        async with self.transactions.begin():
            return await self.run_repo.list_runs(suite_revision_id, run_status)

    async def get_run_record(self, run_id: UUID) -> EvaluationRunRecord | None:
        """Get a run record for display."""
        async with self.transactions.begin():
            run = await self.run_repo.get_run(run_id)
            if run is None:
                return None
            run = await self._full_run(run)
            suite = await self.suite_repo.get_revision(run.suite_revision_id)

        # Check for completed cases (not pending)
        completed_count = sum(
            1 for cr in run.per_case_results if cr.status != CaseResultStatus.PENDING
        )

        return EvaluationRunRecord(
            run_id=run.run_id,
            suite_revision_id=run.suite_revision_id,
            suite_name=suite.suite_name if suite else "Unknown",
            revision_number=suite.revision_number if suite else 0,
            status=run.status.value,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_message=run.error_message,
            baseline_profile_ids=run.baseline_profile_ids,
            candidate_profile_ids=run.candidate_profile_ids,
            config_fingerprints=run.config_fingerprints,
            k_values=run.k_values,
            case_count=len(run.per_case_results),
            completed_case_count=completed_count,
            evaluation_mode=run.evaluation_mode,
            comparison_valid=run.comparison_valid,
            tenant_id=suite.evaluation_tenant_id if suite else None,
        )

    async def create_gate_review(
        self,
        run_id: UUID,
        operator_id: UUID,
        decision: str,
        reason: str,
        reviewed_run_id: UUID,
    ) -> UUID:
        """Create a gate review decision."""
        if decision not in ("approve", "reject"):
            raise GateReviewError("Decision must be 'approve' or 'reject'")

        if not reason.strip() or len(reason) > 1000:
            raise GateReviewError("Reason must be 1-1000 characters")

        # Verify run exists and is completed
        async with self.transactions.begin():
            run = await self.run_repo.get_run(run_id)
            if run is None:
                raise GateReviewError("Run not found")
            run = await self._full_run(run)
            if run.status != RunStatus.COMPLETED or not run.comparison_valid:
                raise GateReviewError("Can only review completed runs")
            if run.run_id != reviewed_run_id:
                raise GateReviewError("Review must name the exact evaluated run")
            if await self.review_repo.get_for_run(run_id) is not None:
                raise GateReviewError("This run already has a gate decision")
            variants = {
                (item.case_id, item.variant)
                for item in run.per_case_results
                if item.status == CaseResultStatus.COMPLETED
            }
            suite = await self.suite_repo.get_revision(run.suite_revision_id)
            if suite is not None:
                suite = await self._full_suite(suite)
            if suite is None or any(
                (case.case_id, variant) not in variants
                for case in suite.test_cases
                for variant in ("baseline", "candidate")
            ):
                raise GateReviewError("Every case must finish for baseline and candidate")
            if decision == "approve" and any(
                item.answer_quality_score is None
                for item in run.per_case_results
                if item.variant == "candidate"
            ):
                raise GateReviewError("Review the quality of every candidate answer first")
            review = GateReview(
                review_id=uuid4(),
                run_id=run_id,
                operator_id=operator_id,
                decision=decision,
                reason=reason.strip(),
                reviewed_run_id=reviewed_run_id,
                created_at=_now_iso(),
            )
            await self.review_repo.create(review)

        return review.review_id

    async def get_gate_review(self, run_id: UUID) -> GateReview | None:
        """Get the gate review for a run."""
        async with self.transactions.begin():
            return await self.review_repo.get_for_run(run_id)

    async def review_answer_quality(
        self, run_id: UUID, result_id: UUID, score: float, note: str
    ) -> None:
        """Save one bounded human quality score against an immutable case result."""
        if not 0.0 <= score <= 1.0 or len(note.strip()) > 2000:
            raise EvaluationError("Quality score must be 0-1 and note at most 2000 characters")
        async with self.transactions.begin():
            run = await self.run_repo.get_run(run_id)
            if run is None or run.status != RunStatus.COMPLETED:
                raise EvaluationError("Only completed runs can receive quality reviews")
            run = await self._full_run(run)
            if await self.review_repo.get_for_run(run_id) is not None:
                raise EvaluationError("A gate decision has already been recorded")
            result = next(
                (item for item in run.per_case_results if item.result_id == result_id), None
            )
            if result is None or result.answer_quality_score is not None:
                raise EvaluationError("Case result is unavailable or already reviewed")
            await self.case_repo.set_answer_quality(result_id, score, note.strip())

    def _validate_test_case(
        self, data: dict[str, Any], index: int, corpus_version_ids: tuple[UUID, ...]
    ) -> EvaluationTestCase:
        """Convert untrusted JSON to one typed case before persistence."""
        if not isinstance(data, dict) or set(data) - _CASE_KEYS:
            raise EvaluationError("Test cases may contain only the fixed suite fields")
        question = data.get("question")
        raw_identity = data.get("authorized_identity_id")
        raw_answerability = data.get("answerability")
        raw_tags = data.get("tags", {})
        raw_anchors = data.get("relevant_passage_ids", [])
        if not isinstance(question, str) or not question.strip():
            raise EvaluationError("Each case needs a nonempty question")
        try:
            identity = UUID(str(raw_identity))
            answerability = Answerability(str(raw_answerability))
        except (ValueError, TypeError) as error:
            raise EvaluationError("Each case needs a valid identity and answerability") from error
        if not isinstance(raw_tags, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_tags.items()
        ):
            raise EvaluationError("Case tags must be string pairs")
        if not isinstance(raw_anchors, list) or not all(
            isinstance(anchor, str) and anchor for anchor in raw_anchors
        ):
            raise EvaluationError("Relevant passage anchors must be strings")
        try:
            anchors = tuple(SourceSpan.parse(anchor) for anchor in raw_anchors)
        except (ValueError, TypeError) as error:
            raise EvaluationError(
                "Relevant passage anchors must use version@page:start:end"
            ) from error
        if any(anchor.document_version_id not in corpus_version_ids for anchor in anchors):
            raise EvaluationError("A relevant span is outside the evaluation corpus")
        relevance_complete = data.get("relevance_complete")
        if not isinstance(relevance_complete, bool):
            raise EvaluationError("Each case must state whether relevance labels are complete")
        if answerability is Answerability.UNANSWERABLE and anchors:
            raise EvaluationError("Unanswerable cases cannot have relevant passages")
        if answerability is Answerability.ANSWERABLE and relevance_complete and not anchors:
            raise EvaluationError("Complete answerable cases need relevant passages")
        filter_text = data.get("filter_text")
        if filter_text is not None and not isinstance(filter_text, str):
            raise EvaluationError("Case filter must be text")
        expected_facts = data.get("expected_facts")
        if expected_facts is not None and not isinstance(expected_facts, dict):
            raise EvaluationError("Expected facts must be an object")
        rubric = data.get("review_rubric")
        if rubric is not None and not isinstance(rubric, str):
            raise EvaluationError("Review rubric must be text")
        return EvaluationTestCase(
            case_id=uuid4(),
            suite_revision_id=UUID(int=0),
            question=question.strip(),
            filter_text=filter_text,
            authorized_identity_id=identity,
            answerability=answerability,
            expected_facts=expected_facts,
            review_rubric=rubric,
            tags=raw_tags,
            relevant_passage_ids=tuple(raw_anchors),
            sort_order=index,
            relevance_complete=relevance_complete,
        )

    async def _build_config_fingerprints(
        self,
        baseline_ids: tuple[UUID, ...],
        candidate_ids: tuple[UUID, ...],
    ) -> dict[str, str]:
        """Hash immutable bundle and capability snapshot contents for audit."""
        return {
            "baseline": await self._query_fingerprint(baseline_ids[0]),
            "candidate": await self._query_fingerprint(candidate_ids[0]),
        }

    async def _read_cohorts(
        self, baseline_id: UUID, candidate_id: UUID
    ) -> dict[str, tuple[UUID, ...]]:
        if self.query_profiles is None:
            raise EvaluationError("Query profile reader is unavailable")
        baseline = await self.query_profiles.get(baseline_id)
        candidate = await self.query_profiles.get(candidate_id)
        if baseline is None or candidate is None:
            raise EvaluationError("Query policy is unavailable")
        return {
            "baseline_lexical": baseline.lexical_profile_ids,
            "baseline_embedding": baseline.embedding_profile_ids,
            "candidate_lexical": candidate.lexical_profile_ids,
            "candidate_embedding": candidate.embedding_profile_ids,
        }

    async def _query_fingerprint(self, profile_id: UUID) -> str:
        if (
            self.query_profiles is None
            or self.capability_profiles is None
            or self.snapshots is None
        ):
            raise EvaluationError("Profile snapshot readers are unavailable")
        profile = await self.query_profiles.get(profile_id)
        if profile is None:
            raise EvaluationError("Query policy is unavailable")
        components: list[dict[str, object]] = []
        for capability_id in (
            *profile.lexical_profile_ids,
            *profile.embedding_profile_ids,
            profile.reranker_profile_id,
            profile.generation_profile_id,
        ):
            capability = await self.capability_profiles.get(capability_id)
            if capability is None:
                raise EvaluationError("Query policy capability is unavailable")
            snapshot = await self.snapshots.get(capability.configuration_snapshot_id)
            if snapshot is None:
                raise EvaluationError("Query policy snapshot is unavailable")
            components.append(
                {
                    "id": str(capability_id),
                    "capability": capability.capability,
                    "configuration": snapshot.configuration,
                }
            )
        retrieval = await self.snapshots.get(profile.retrieval_snapshot_id)
        if retrieval is None:
            raise EvaluationError("Query retrieval snapshot is unavailable")
        payload = {
            "profile_id": str(profile_id),
            "components": components,
            "retrieval": retrieval.configuration,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _require_ingestion_cohorts(self, manifest: EvaluationCorpusManifest) -> None:
        """Ensure the evaluated query bundle can read both ingestion generations."""
        if self.query_profiles is None or self.ingestion_profiles is None:
            raise EvaluationError("Profile readers are unavailable")
        query = await self.query_profiles.get(manifest.candidate_query_profile_id)
        baseline_id = manifest.baseline_ingestion_profile_id
        candidate_id = manifest.candidate_ingestion_profile_id
        if query is None or baseline_id is None or candidate_id is None:
            raise EvaluationError("Comparison profiles are unavailable")
        for ingestion_id in (baseline_id, candidate_id):
            ingestion = await self.ingestion_profiles.get(ingestion_id)
            if ingestion is None or (
                ingestion.lexical_profile_id not in query.lexical_profile_ids
                or ingestion.embedding_profile_id not in query.embedding_profile_ids
            ):
                raise EvaluationError("Query policy must read both ingestion cohorts")

    async def _ingestion_fingerprint(self, profile_id: UUID) -> str:
        if (
            self.ingestion_profiles is None
            or self.capability_profiles is None
            or self.snapshots is None
        ):
            raise EvaluationError("Ingestion snapshot readers are unavailable")
        profile = await self.ingestion_profiles.get(profile_id)
        if profile is None:
            raise EvaluationError("Ingestion policy is unavailable")
        components: list[dict[str, object]] = []
        for capability_id in (
            profile.ner_profile_id,
            profile.chunking_profile_id,
            profile.lexical_profile_id,
            profile.embedding_profile_id,
        ):
            capability = await self.capability_profiles.get(capability_id)
            if capability is None:
                raise EvaluationError("Ingestion capability is unavailable")
            snapshot = await self.snapshots.get(capability.configuration_snapshot_id)
            if snapshot is None:
                raise EvaluationError("Ingestion snapshot is unavailable")
            components.append(
                {
                    "id": str(capability_id),
                    "capability": capability.capability,
                    "configuration": snapshot.configuration,
                }
            )
        payload = {"profile_id": str(profile_id), "components": components}
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    from datetime import datetime

    return datetime.now(UTC).isoformat()
