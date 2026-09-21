"""Unit tests for query authorization and profile preparation."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from document_insight.application.auth.models import AuthorizationContext, UserRole
from document_insight.application.query.commands import PrepareQueryCommand
from document_insight.application.query.exceptions import QueryProfileUnavailableError
from document_insight.application.query.service import QueryPreparationService
from document_insight.infrastructure.query_profile.protocol import ResolvedQueryProfile


@dataclass
class FakeActiveProfiles:
    """In-memory active profile selection."""

    profile_id: UUID | None

    async def get_query_profile_id(self, scope: str) -> UUID | None:
        assert scope == "platform"
        return self.profile_id


@dataclass
class FakeQueryProfiles:
    """In-memory query profile lookup."""

    profile: ResolvedQueryProfile | None

    async def get(self, query_profile_id: UUID) -> ResolvedQueryProfile | None:
        return (
            self.profile
            if self.profile and self.profile.query_profile_id == query_profile_id
            else None
        )


@dataclass
class FakeDepartments:
    """In-memory tenant department listing."""

    department_ids: tuple[UUID, ...]

    async def list_all_ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        return self.department_ids


@pytest.mark.anyio
async def test_prepare_keeps_the_admins_complete_tenant_department_scope() -> None:
    """Textual retrieval hints never change an admin's authorization scope."""
    tenant_id, finance_id, legal_id, profile_id = (uuid4() for _ in range(4))
    service = QueryPreparationService(
        active_profiles=FakeActiveProfiles(profile_id),
        query_profiles=FakeQueryProfiles(ResolvedQueryProfile(profile_id, (uuid4(),), (uuid4(),))),
        departments=FakeDepartments((finance_id, legal_id)),
    )
    prepared = await service.prepare(
        PrepareQueryCommand(
            question="What changed?",
            filter_text="vendor contract",
            top_k=5,
            actor=AuthorizationContext(uuid4(), tenant_id, (finance_id,), UserRole.TENANT_ADMIN),
        )
    )

    assert prepared.department_ids == (finance_id, legal_id)
    assert prepared.filter_text == "vendor contract"
    assert prepared.lexical_profile_ids
    assert prepared.embedding_profile_ids


@pytest.mark.anyio
async def test_prepare_requires_an_explicit_active_query_profile() -> None:
    """Query preparation never falls back to deployment configuration."""
    service = QueryPreparationService(
        active_profiles=FakeActiveProfiles(None),
        query_profiles=FakeQueryProfiles(None),
        departments=FakeDepartments(()),
    )
    command = PrepareQueryCommand(
        "Question", None, 5, AuthorizationContext(uuid4(), uuid4(), (), UserRole.VIEWER)
    )

    with pytest.raises(QueryProfileUnavailableError):
        await service.prepare(command)
