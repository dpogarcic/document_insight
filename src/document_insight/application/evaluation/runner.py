"""Execute persisted evaluation runs through the production query path."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from document_insight.application.evaluation.corpus import EvaluationCorpusValidator
from document_insight.application.evaluation.executor import QueryEvaluationExecutor
from document_insight.application.evaluation.models import EvaluationCorpusManifest, TestCaseResult
from document_insight.application.evaluation.scoring import (
    ScoredMetric,
    SourceSpan,
    aggregate_metrics,
    citation_metrics,
    retrieval_metrics,
)
from document_insight.application.evaluation.service import EvaluationService
from document_insight.infrastructure.evaluation_aggregate.protocol import AggregateMeasurement
from document_insight.infrastructure.evaluation_test_case.protocol import EvaluationTestCase

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CaseMeasurement:
    variant: str
    metrics: tuple[ScoredMetric, ...]


class EvaluationRunner:
    """Run two immutable query bundles over one tenant's selected corpus."""

    def __init__(
        self,
        service: EvaluationService,
        executor: QueryEvaluationExecutor,
        corpus_validator: EvaluationCorpusValidator,
    ) -> None:
        self._service = service
        self._executor = executor
        self._corpus_validator = corpus_validator

    async def run(self, run_id: UUID) -> None:
        """Claim one durable run, save each result, then publish auditable aggregates."""
        if not await self._service.claim_run(run_id):
            return
        try:
            run = await self._service.get_run(run_id)
            if run is None:
                raise ValueError("Evaluation run is unavailable")
            suite = await self._service.get_suite_revision(run.suite_revision_id)
            if suite is None or suite.evaluation_tenant_id is None:
                raise ValueError("Evaluation suite is unavailable")
            manifest = EvaluationCorpusManifest.from_json(run.corpus_manifest)
            if run.corpus_manifest.get("evaluation_tenant_id") != str(suite.evaluation_tenant_id):
                raise ValueError("Evaluation run tenant differs from its suite")
            if manifest.suite_fingerprint != suite.dataset_fingerprint:
                raise ValueError("Evaluation suite changed after run creation")
            await self._corpus_validator.validate(suite, manifest)
            measurements: dict[str, list[tuple[ScoredMetric, ...]]] = {
                "baseline": [],
                "candidate": [],
            }
            for case in suite.test_cases:
                for variant, profile_id, corpus in (
                    ("baseline", manifest.baseline_query_profile_id, manifest.baseline),
                    ("candidate", manifest.candidate_query_profile_id, manifest.candidate),
                ):
                    started_at = _now_iso()
                    result = await self._executor.execute(
                        case,
                        profile_id,
                        corpus.version_ids,
                        corpus.source_versions,
                        top_k=max(run.k_values),
                    )
                    scored = _score_case(case, result, run.k_values)
                    measurements[variant].append(scored)
                    await self._service.add_case_result(
                        run_id,
                        case.case_id,
                        result.status,
                        result.lexical_ranked_ids,
                        result.vector_cohort_ranked_ids,
                        result.vector_combined_ranked_ids,
                        result.fused_ranked_ids,
                        result.reranked_ranked_ids,
                        result.final_citations,
                        result.answer_text,
                        result.answerability_outcome,
                        result.provider_errors,
                        result.stage_latencies_ms,
                        started_at,
                        _now_iso(),
                        variant,
                        tuple(_metric_dict(item) for item in scored),
                        result.lexical_cohort_ranked_ids,
                    )
                    await self._service.touch_heartbeat(run_id)
            for variant, case_values in measurements.items():
                for metric in aggregate_metrics(tuple(case_values)):
                    await self._service.add_aggregate(
                        run_id,
                        AggregateMeasurement(
                            uuid4(),
                            run_id,
                            metric.name,
                            metric.value,
                            sum(
                                any(_same_key(metric, item) for item in case)
                                for case in case_values
                            ),
                            metric.numerator,
                            metric.denominator,
                            metric.definition,
                            variant,
                            metric.stage,
                            metric.k,
                            metric.cohort_id,
                        ),
                    )
            await self._service.update_run_status(run_id, "completed", completed_at=_now_iso())
        except Exception:
            # The exception may contain document text, prompt contents, or provider payloads.
            # Retain only a safe operational message in PostgreSQL and structured logs.
            logger.error("Evaluation run failed", extra={"run_id": str(run_id)})
            await self._service.update_run_status(
                run_id,
                "failed",
                completed_at=_now_iso(),
                error_message="Evaluation failed; inspect provider availability and approved corpus",
            )
            raise


def _same_key(left: ScoredMetric, right: ScoredMetric) -> bool:
    return (left.name, left.stage, left.k, left.cohort_id) == (
        right.name,
        right.stage,
        right.k,
        right.cohort_id,
    )


def _metric_dict(metric: ScoredMetric) -> dict[str, object]:
    return {
        "name": metric.name,
        "stage": metric.stage,
        "k": metric.k,
        "cohort_id": str(metric.cohort_id) if metric.cohort_id else None,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
        "value": metric.value,
        "definition": metric.definition,
    }


def _score_case(
    case: EvaluationTestCase, result: TestCaseResult, k_values: tuple[int, ...]
) -> tuple[ScoredMetric, ...]:
    gold = tuple(SourceSpan.parse(value) for value in case.relevant_passage_ids)
    scored: list[ScoredMetric] = []
    stages = {
        "lexical": result.lexical_ranked_ids,
        "vector": result.vector_combined_ranked_ids,
        "fused": result.fused_ranked_ids,
        "reranked": result.reranked_ranked_ids,
    }
    for stage, anchors in stages.items():
        scored.extend(
            retrieval_metrics(
                tuple(SourceSpan.parse(value) for value in anchors),
                gold,
                k_values,
                stage=stage,
                complete_relevance_set=case.relevance_complete,
            )
        )
    for kind, cohorts in (
        ("lexical", result.lexical_cohort_ranked_ids or {}),
        ("vector", result.vector_cohort_ranked_ids),
    ):
        for cohort_id, anchors in cohorts.items():
            scored.extend(
                retrieval_metrics(
                    tuple(SourceSpan.parse(value) for value in anchors),
                    gold,
                    k_values,
                    stage=kind,
                    complete_relevance_set=case.relevance_complete,
                    cohort_id=UUID(cohort_id),
                )
            )
    scored.extend(
        citation_metrics(
            tuple(
                SourceSpan.parse(str(value["source_anchor"])) for value in result.final_citations
            ),
            gold,
            complete_relevance_set=case.relevance_complete,
        )
    )
    answered = result.answerability_outcome == "answered"
    correct = answered == (case.answerability.value == "answerable")
    scored.append(
        ScoredMetric(
            "answerability_accuracy",
            "answer",
            None,
            int(correct),
            1,
            float(correct),
            "Correct answered versus refused outcome divided by evaluated cases.",
        )
    )
    return tuple(scored)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
