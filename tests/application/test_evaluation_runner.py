"""Persisted evaluation runner uses actual captured stage results and safe state changes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from document_insight.application.evaluation.models import (
    CorpusVariant,
    EvaluationCorpusManifest,
)
from document_insight.application.evaluation.models import (
    TestCaseResult as CaseResult,
)
from document_insight.application.evaluation.runner import EvaluationRunner
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_runner_scores_baseline_and_candidate_and_completes() -> None:
    source_id = uuid4()
    case_id = uuid4()
    baseline_id, candidate_id = uuid4(), uuid4()
    anchor = f"{source_id}@1:0:100"
    case = EvaluationTestCase(
        case_id,
        uuid4(),
        "What is the answer?",
        None,
        uuid4(),
        Answerability.ANSWERABLE,
        None,
        None,
        {},
        (anchor,),
        0,
        True,
    )
    corpus = CorpusVariant((source_id,), {source_id: source_id})
    manifest = EvaluationCorpusManifest("a" * 64, corpus, corpus, baseline_id, candidate_id)
    tenant_id = uuid4()
    run = SimpleNamespace(
        suite_revision_id=case.suite_revision_id,
        corpus_manifest={**manifest.to_json(), "evaluation_tenant_id": str(tenant_id)},
        k_values=(1, 5),
    )
    suite = SimpleNamespace(
        evaluation_tenant_id=tenant_id, dataset_fingerprint="a" * 64, test_cases=(case,)
    )
    service = SimpleNamespace(
        claim_run=AsyncMock(return_value=True),
        get_run=AsyncMock(return_value=run),
        get_suite_revision=AsyncMock(return_value=suite),
        add_case_result=AsyncMock(),
        add_aggregate=AsyncMock(),
        touch_heartbeat=AsyncMock(),
        update_run_status=AsyncMock(),
    )
    result = CaseResult(
        case_id,
        "completed",
        (anchor,),
        {},
        (anchor,),
        (anchor,),
        (anchor,),
        ({"source_anchor": anchor},),
        "Grounded answer",
        "answered",
        (),
        {"total": 1.0},
    )
    executor = SimpleNamespace(execute=AsyncMock(return_value=result))
    run_id = uuid4()
    validator = SimpleNamespace(validate=AsyncMock())
    await EvaluationRunner(service, executor, validator).run(run_id)

    assert executor.execute.await_count == 2
    assert service.add_case_result.await_count == 2
    assert service.add_aggregate.await_count > 0
    assert service.update_run_status.await_args.args[:2] == (run_id, "completed")
    assert all(call.args[2] == "completed" for call in service.add_case_result.await_args_list)


@pytest.mark.anyio
async def test_runner_keeps_failure_message_content_free() -> None:
    service = SimpleNamespace(
        claim_run=AsyncMock(return_value=True),
        get_run=AsyncMock(side_effect=RuntimeError("secret document text")),
        update_run_status=AsyncMock(),
    )
    with pytest.raises(RuntimeError):
        await EvaluationRunner(service, SimpleNamespace(), SimpleNamespace()).run(uuid4())
    assert (
        "secret document text" not in service.update_run_status.await_args.kwargs["error_message"]
    )


@pytest.mark.anyio
async def test_runner_rejects_run_moved_to_another_tenant() -> None:
    tenant_id = uuid4()
    source_id = uuid4()
    corpus = CorpusVariant((source_id,), {source_id: source_id})
    manifest = EvaluationCorpusManifest("a" * 64, corpus, corpus, uuid4(), uuid4())
    service = SimpleNamespace(
        claim_run=AsyncMock(return_value=True),
        get_run=AsyncMock(
            return_value=SimpleNamespace(
                suite_revision_id=uuid4(),
                corpus_manifest={**manifest.to_json(), "evaluation_tenant_id": str(uuid4())},
            )
        ),
        get_suite_revision=AsyncMock(return_value=SimpleNamespace(evaluation_tenant_id=tenant_id)),
        update_run_status=AsyncMock(),
    )
    validator = SimpleNamespace(validate=AsyncMock())
    with pytest.raises(ValueError, match="tenant differs"):
        await EvaluationRunner(service, SimpleNamespace(), validator).run(uuid4())
    validator.validate.assert_not_awaited()
    assert service.update_run_status.await_args.args[1] == "failed"
