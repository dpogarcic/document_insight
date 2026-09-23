"""Seeded evaluation scenarios remain reusable across corpus revisions."""

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from document_insight.infrastructure.evaluation_case_template.repository import (
    SqlAlchemyEvaluationCaseTemplateRepository,
)


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_runtime_url: str | None = None
    test_database_owner_password: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_seeded_templates_cover_answerable_unanswerable_and_access_cases() -> None:
    settings = _Settings()
    if not settings.test_database_runtime_url or not settings.test_database_owner_password:
        pytest.skip("Disposable test PostgreSQL is unavailable")
    owner_url = make_url(settings.test_database_runtime_url).set(
        username="document_insight_test_owner",
        password=settings.test_database_owner_password,
    )
    engine = create_async_engine(owner_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            templates = await SqlAlchemyEvaluationCaseTemplateRepository(session).list_all()
        assert len(templates) == 10
        assert len({template.key for template in templates}) == len(templates)
        assert {template.answerability for template in templates} == {"answerable", "unanswerable"}
        assert {template.scenario_tag for template in templates} >= {
            "authorization",
            "abstention",
            "multi_passage",
            "precision",
            "filter",
        }
        assert all(template.review_rubric for template in templates)
    finally:
        await engine.dispose()
