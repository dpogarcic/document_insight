"""Evaluation history is writable by the restricted operator and reloads from PostgreSQL."""

from uuid import uuid4

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.evaluation_aggregate.protocol import AggregateMeasurement
from document_insight.infrastructure.evaluation_aggregate.repository import (
    SqlAlchemyEvaluationAggregateRepository,
)
from document_insight.infrastructure.evaluation_case_result.protocol import (
    CaseResultStatus,
    EvaluationCaseResult,
)
from document_insight.infrastructure.evaluation_case_result.repository import (
    SqlAlchemyEvaluationCaseResultRepository,
)
from document_insight.infrastructure.evaluation_gate_review.protocol import GateReview
from document_insight.infrastructure.evaluation_gate_review.repository import (
    SqlAlchemyEvaluationGateReviewRepository,
)
from document_insight.infrastructure.evaluation_run.protocol import EvaluationRun, RunStatus
from document_insight.infrastructure.evaluation_run.repository import (
    SqlAlchemyEvaluationRunRepository,
)
from document_insight.infrastructure.evaluation_suite.repository import (
    SqlAlchemyEvaluationSuiteRepository,
)
from document_insight.infrastructure.evaluation_test_case.protocol import (
    Answerability,
    EvaluationTestCase,
)
from document_insight.infrastructure.evaluation_test_case.repository import (
    SqlAlchemyEvaluationTestCaseRepository,
)


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_operator_persists_suite_run_metrics_and_review() -> None:
    settings = _Settings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable test PostgreSQL is unavailable")
    owner_url = make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    engine = create_async_engine(owner_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    revision_id = None
    run_id = uuid4()
    case_id = uuid4()
    source_id = uuid4()
    try:
        async with sessions() as session:
            async with session.begin():
                await session.execute(text("SET LOCAL ROLE di_profile_operator"))
                suites = SqlAlchemyEvaluationSuiteRepository(session)
                runs = SqlAlchemyEvaluationRunRepository(session)
                cases = SqlAlchemyEvaluationTestCaseRepository(session)
                results = SqlAlchemyEvaluationCaseResultRepository(session)
                aggregates = SqlAlchemyEvaluationAggregateRepository(session)
                reviews = SqlAlchemyEvaluationGateReviewRepository(session)
                case = EvaluationTestCase(
                    case_id,
                    uuid4(),
                    "What changed?",
                    None,
                    uuid4(),
                    Answerability.ANSWERABLE,
                    None,
                    None,
                    {},
                    (f"{source_id}@1:0:100",),
                    0,
                    True,
                )
                revision_id = await suites.create_revision(
                    f"test-{uuid4()}",
                    uuid4(),
                    uuid4(),
                    (source_id,),
                    "a" * 64,
                )
                await cases.create_many(revision_id, (case,))
                await runs.create_run(
                    EvaluationRun(
                        run_id,
                        revision_id,
                        {"suite_fingerprint": "a" * 64},
                        (uuid4(),),
                        (uuid4(),),
                        {"baseline": "b" * 64, "candidate": "c" * 64},
                        {},
                        None,
                        "test-v1",
                        (1,),
                        uuid4(),
                        "query",
                        RunStatus.PENDING,
                        None,
                        None,
                        None,
                        (),
                        (),
                        True,
                    )
                )
                await session.flush()
                await results.add(
                    EvaluationCaseResult(
                        uuid4(),
                        run_id,
                        case_id,
                        CaseResultStatus.COMPLETED,
                        (f"{source_id}@1:0:100",),
                        {},
                        (),
                        (),
                        (),
                        (),
                        None,
                        "answered",
                        (),
                        {},
                        "2026-09-23T00:00:00+00:00",
                        "2026-09-23T00:00:01+00:00",
                    )
                )
                await aggregates.add(
                    AggregateMeasurement(
                        uuid4(),
                        run_id,
                        "precision",
                        1.0,
                        1,
                        1,
                        1,
                        "Relevant / K",
                        "candidate",
                        "reranked",
                        1,
                    )
                )
                await reviews.create(
                    GateReview(
                        uuid4(),
                        run_id,
                        uuid4(),
                        "approve",
                        "Reviewed answer",
                        run_id,
                        "2026-09-23T00:00:02+00:00",
                    )
                )
        async with sessions() as session:
            async with session.begin():
                await session.execute(text("SET LOCAL ROLE di_profile_operator"))
                suites = SqlAlchemyEvaluationSuiteRepository(session)
                runs = SqlAlchemyEvaluationRunRepository(session)
                cases = SqlAlchemyEvaluationTestCaseRepository(session)
                results = SqlAlchemyEvaluationCaseResultRepository(session)
                aggregates = SqlAlchemyEvaluationAggregateRepository(session)
                reviews = SqlAlchemyEvaluationGateReviewRepository(session)
                suite = await suites.get_revision(revision_id)
                run = await runs.get_run(run_id)
                review = await reviews.get_for_run(run_id)
                assert (
                    suite is not None
                    and (await cases.list_for_revision(revision_id))[0].case_id == case_id
                )
                assert (
                    run is not None and (await results.list_for_run(run_id))[0].case_id == case_id
                )
                assert (await aggregates.list_for_run(run_id))[0].metric_value == 1.0
                assert review is not None and review.decision == "approve"
    finally:
        if revision_id is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM evaluation_runs WHERE id = :id"), {"id": run_id}
                )
                await connection.execute(
                    text("DELETE FROM evaluation_suite_revisions WHERE id = :id"),
                    {"id": revision_id},
                )
        await engine.dispose()


@pytest.mark.anyio
async def test_test_tenant_ingestion_selection_is_readable_by_api_write_role() -> None:
    settings = _Settings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable test PostgreSQL is unavailable")
    owner_url = make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    engine = create_async_engine(owner_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope = f"evaluation:{uuid4()}"
    try:
        async with sessions() as session:
            async with session.begin():
                await session.execute(text("SET LOCAL ROLE di_profile_operator"))
                active = SqlAlchemyActiveProfileRepository(session)
                platform = await active.get("platform", "ingestion")
                assert platform is not None
                await active.create_evaluation_ingestion(scope, platform.profile_id)
        async with sessions() as session:
            async with session.begin():
                await session.execute(text("SET LOCAL ROLE di_api_write"))
                selected = await SqlAlchemyActiveProfileRepository(
                    session
                ).get_ingestion_profile_id(scope)
                assert selected == platform.profile_id
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM active_profiles WHERE scope = :scope"), {"scope": scope}
            )
        await engine.dispose()


@pytest.mark.anyio
async def test_suite_revision_names_are_scoped_to_tenant() -> None:
    """Two tenants can start the same named suite at revision one."""
    settings = _Settings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable test PostgreSQL is unavailable")
    owner_url = make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    engine = create_async_engine(owner_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("SET LOCAL ROLE di_profile_operator"))
                async with async_sessionmaker(connection, expire_on_commit=False)() as session:
                    suites = SqlAlchemyEvaluationSuiteRepository(session)
                    first_tenant, second_tenant = uuid4(), uuid4()
                    name = f"shared-{uuid4()}"
                    first = await suites.create_revision(
                        name, uuid4(), first_tenant, (uuid4(),), "a" * 64
                    )
                    second = await suites.create_revision(
                        name, uuid4(), second_tenant, (uuid4(),), "b" * 64
                    )
                    assert (await suites.get_revision(first)).revision_number == 1
                    assert (await suites.get_revision(second)).revision_number == 1
                    assert len(await suites.list_revisions(name, first_tenant)) == 1
                    assert len(await suites.list_revisions(name, second_tenant)) == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
