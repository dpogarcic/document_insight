"""Dedicated evaluation worker using the same authorized query adapters as the API."""

import asyncio
from uuid import UUID

from document_insight.application.evaluation.corpus import EvaluationCorpusValidator
from document_insight.application.evaluation.executor import QueryEvaluationExecutor
from document_insight.application.evaluation.runner import EvaluationRunner
from document_insight.application.evaluation.service import EvaluationService
from document_insight.application.query.profile_resolver import QueryProfileResolver
from document_insight.application.query.service import QueryPreparationService
from document_insight.config import get_settings
from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.department.repository import SqlAlchemyDepartmentRepository
from document_insight.infrastructure.document.repository import SqlAlchemyDocumentRepository
from document_insight.infrastructure.document_version.repository import (
    SqlAlchemyDocumentVersionRepository,
)
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
from document_insight.infrastructure.generation.mistral import MistralGroundedAnswerGeneratorFactory
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.mistral.embedding import MistralTextEmbedderFactory
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)
from document_insight.infrastructure.reranker.mistral import MistralRerankerFactory
from document_insight.infrastructure.retrieval.repository import (
    SqlAlchemyAuthorizedRetrievalRepository,
)
from document_insight.infrastructure.security.evaluation_actor import (
    SqlAlchemyEvaluationActorLoader,
)
from document_insight.infrastructure.user.repository import SqlAlchemyUserRepository
from document_insight.infrastructure.user_department.repository import (
    SqlAlchemyUserDepartmentRepository,
)


def process_evaluation_run(run_id: str) -> None:
    """RQ entry point; duplicate deliveries cannot claim the same run twice."""
    asyncio.run(_process(UUID(run_id)))


async def _process(run_id: UUID) -> None:
    settings = get_settings()
    if settings.mistral_api_key is None:
        raise RuntimeError("Evaluation provider credential must be configured")
    async with get_session_factory("profile_operator")() as operator_session:
        async with get_session_factory("read")() as read_session:
            service = EvaluationService(
                SqlAlchemyEvaluationSuiteRepository(operator_session),
                SqlAlchemyEvaluationRunRepository(operator_session),
                SqlAlchemyTransactionManager(operator_session),
                SqlAlchemyEvaluationCaseResultRepository(operator_session),
                SqlAlchemyEvaluationAggregateRepository(operator_session),
                SqlAlchemyEvaluationGateReviewRepository(operator_session),
                SqlAlchemyEvaluationTestCaseRepository(operator_session),
            )
            run = await service.get_run(run_id)
            suite = None if run is None else await service.get_suite_revision(run.suite_revision_id)
            if suite is None or suite.evaluation_tenant_id is None:
                raise ValueError("Evaluation run has no selected tenant")
            tenant_id = suite.evaluation_tenant_id
            key = settings.mistral_api_key.get_secret_value()
            query = QueryPreparationService(
                SqlAlchemyActiveProfileRepository(read_session),
                QueryProfileResolver(
                    SqlAlchemyQueryProfileRepository(read_session),
                    SqlAlchemyCapabilityProfileRepository(read_session),
                    SqlAlchemyConfigurationSnapshotRepository(read_session),
                ),
                SqlAlchemyDepartmentRepository(read_session),
                SqlAlchemyAuthorizedRetrievalRepository(read_session),
                MistralTextEmbedderFactory(settings.mistral_base_url, key),
                MistralRerankerFactory(settings.mistral_base_url, key),
                MistralGroundedAnswerGeneratorFactory(settings.mistral_base_url, key),
            )
            actors = SqlAlchemyEvaluationActorLoader(
                read_session,
                SqlAlchemyUserRepository(read_session),
                SqlAlchemyUserDepartmentRepository(read_session),
                tenant_id,
            )
            await EvaluationRunner(
                service,
                QueryEvaluationExecutor(query, actors, tenant_id),
                EvaluationCorpusValidator(
                    actors,
                    SqlAlchemyDocumentRepository(read_session),
                    SqlAlchemyDocumentVersionRepository(read_session),
                    SqlAlchemyIndexGenerationRepository(read_session),
                    tenant_id,
                ),
            ).run(run_id)
