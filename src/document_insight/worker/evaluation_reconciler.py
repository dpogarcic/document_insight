"""Repair evaluation runs committed before an RQ publication failure."""

import asyncio
from datetime import UTC, datetime, timedelta

from document_insight.application.evaluation.service import EvaluationService
from document_insight.config import get_settings
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.evaluation_aggregate.repository import (
    SqlAlchemyEvaluationAggregateRepository,
)
from document_insight.infrastructure.evaluation_case_result.repository import (
    SqlAlchemyEvaluationCaseResultRepository,
)
from document_insight.infrastructure.evaluation_gate_review.repository import (
    SqlAlchemyEvaluationGateReviewRepository,
)
from document_insight.infrastructure.evaluation_run.repository import (
    SqlAlchemyEvaluationRunRepository,
)
from document_insight.infrastructure.evaluation_suite.repository import (
    SqlAlchemyEvaluationSuiteRepository,
)
from document_insight.infrastructure.evaluation_test_case.repository import (
    SqlAlchemyEvaluationTestCaseRepository,
)
from document_insight.infrastructure.queue.evaluation import RqEvaluationQueue


async def _run() -> None:
    settings = get_settings()
    queue = RqEvaluationQueue(settings.redis_url, settings.rq_evaluation_queue_name)
    while True:
        async with get_session_factory("profile_operator")() as session:
            service = EvaluationService(
                SqlAlchemyEvaluationSuiteRepository(session),
                SqlAlchemyEvaluationRunRepository(session),
                SqlAlchemyTransactionManager(session),
                SqlAlchemyEvaluationCaseResultRepository(session),
                SqlAlchemyEvaluationAggregateRepository(session),
                SqlAlchemyEvaluationGateReviewRepository(session),
                SqlAlchemyEvaluationTestCaseRepository(session),
            )
            for run_id in await service.list_pending_ids():
                try:
                    await queue.enqueue(run_id)
                    await service.mark_enqueued(run_id)
                except RuntimeError:
                    break
            await service.fail_stale_running((datetime.now(UTC) - timedelta(hours=2)).isoformat())
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(_run())
