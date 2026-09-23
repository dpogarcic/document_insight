"""Initial evaluation identity setup is limited to an empty seeded tenant."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from document_insight.application.auth.models import UserRole
from document_insight.application.evaluation.identity import (
    EvaluationIdentityAlreadyProvisionedError,
    EvaluationIdentityProvisioner,
    EvaluationTenantUnavailableError,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def _transaction():
    yield


@pytest.mark.anyio
async def test_first_admin_receives_existing_test_departments() -> None:
    tenant_id, department_id, user_id = uuid4(), uuid4(), uuid4()
    users = SimpleNamespace(
        has_for_tenant=AsyncMock(return_value=False),
        create=AsyncMock(return_value=SimpleNamespace(user_id=user_id)),
    )
    departments = SimpleNamespace(list_all_ids=AsyncMock(return_value=(department_id,)))
    memberships = SimpleNamespace(add=AsyncMock())
    passwords = SimpleNamespace(hash=Mock(return_value="hashed"))
    service = EvaluationIdentityProvisioner(
        users, departments, memberships, SimpleNamespace(begin=_transaction), passwords
    )

    created = await service.provision(tenant_id, " Admin@Example.com ", "Test Admin", "password123")

    assert created == user_id
    users.create.assert_awaited_once_with(
        tenant_id, "admin@example.com", "Test Admin", "hashed", UserRole.TENANT_ADMIN
    )
    memberships.add.assert_awaited_once_with(user_id, department_id, tenant_id)


@pytest.mark.anyio
async def test_existing_identity_prevents_second_admin() -> None:
    users = SimpleNamespace(has_for_tenant=AsyncMock(return_value=True), create=AsyncMock())
    departments = SimpleNamespace(list_all_ids=AsyncMock())
    service = EvaluationIdentityProvisioner(
        users,
        departments,
        SimpleNamespace(add=AsyncMock()),
        SimpleNamespace(begin=_transaction),
        SimpleNamespace(hash=Mock(return_value="hashed")),
    )
    with pytest.raises(EvaluationIdentityAlreadyProvisionedError):
        await service.provision(uuid4(), "admin@example.com", "Admin", "password123")
    users.create.assert_not_awaited()
    departments.list_all_ids.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_seeded_department_prevents_identity_creation() -> None:
    users = SimpleNamespace(has_for_tenant=AsyncMock(return_value=False), create=AsyncMock())
    service = EvaluationIdentityProvisioner(
        users,
        SimpleNamespace(list_all_ids=AsyncMock(return_value=())),
        SimpleNamespace(add=AsyncMock()),
        SimpleNamespace(begin=_transaction),
        SimpleNamespace(hash=Mock(return_value="hashed")),
    )
    with pytest.raises(EvaluationTenantUnavailableError):
        await service.provision(uuid4(), "admin@example.com", "Admin", "password123")
    users.create.assert_not_awaited()
