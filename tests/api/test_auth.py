"""Registration and login flow tests using an isolated relational database."""

from collections.abc import AsyncIterator

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from document_insight.api.app import create_app
from document_insight.config import Settings, get_settings
from document_insight.infrastructure.database.base import Base
from document_insight.infrastructure.database.models import (
    DepartmentModel,
    TenantModel,
    UserModel,
)
from document_insight.infrastructure.database.session import get_db_session

REGISTER_PAYLOAD = {
    "email": "admin@example.com",
    "password": "correct-horse-battery-staple",
    "display_name": "Tenant Admin",
    "tenant_name": "Example Tenant",
}


@pytest.fixture
def anyio_backend() -> str:
    """Run async API tests on asyncio."""
    return "asyncio"


@pytest.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """Create an API client backed by an isolated in-memory database."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret_key=SecretStr("test-secret-key-that-is-long-enough"),
        jwt_access_token_expire_minutes=30,
    )
    application = create_app()

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    application.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.anyio
async def test_register_provisions_tenant_department_and_hashed_admin(
    auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Registration atomically provisions the initial tenant membership."""
    client, session_factory = auth_client

    response = await client.post("/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "admin@example.com"
    assert body["display_name"] == "Tenant Admin"
    assert body["role"] == "tenant_admin"

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(TenantModel)) == 1
        department = await session.scalar(select(DepartmentModel))
        user = await session.scalar(select(UserModel))

    assert department is not None
    assert department.name == "General"
    assert user is not None
    assert user.tenant_id == department.tenant_id
    assert user.department_id == department.id
    assert user.password_hash != REGISTER_PAYLOAD["password"]
    assert user.password_hash.startswith("$argon2")


@pytest.mark.anyio
async def test_login_returns_token_with_authorization_claims(
    auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Valid credentials issue a signed token with tenant, department, and role claims."""
    client, _ = auth_client
    registration = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    registered_user = registration.json()

    response = await client.post(
        "/auth/login",
        json={
            "email": "ADMIN@example.com",
            "password": REGISTER_PAYLOAD["password"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    claims = jwt.decode(
        body["access_token"],
        "test-secret-key-that-is-long-enough",
        algorithms=["HS256"],
        audience="document-insight-api",
        issuer="document-insight",
    )
    assert claims["sub"] == registered_user["user_id"]
    assert claims["tenant_id"] == registered_user["tenant_id"]
    assert claims["department_ids"] == [registered_user["department_id"]]
    assert claims["role"] == "tenant_admin"
    assert claims["type"] == "access"


@pytest.mark.anyio
async def test_register_rejects_duplicate_email(
    auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Email uniqueness is enforced without exposing persistence errors."""
    client, _ = auth_client
    await client.post("/auth/register", json=REGISTER_PAYLOAD)

    response = await client.post(
        "/auth/register",
        json={**REGISTER_PAYLOAD, "tenant_name": "Another Tenant"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "email_already_registered",
            "message": "An account with this email address already exists.",
        }
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("admin@example.com", "wrong-password"),
        ("missing@example.com", "wrong-password"),
    ],
)
async def test_login_rejects_invalid_credentials_without_user_disclosure(
    auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
    email: str,
    password: str,
) -> None:
    """Incorrect and unknown credentials receive the same public response."""
    client, _ = auth_client
    await client.post("/auth/register", json=REGISTER_PAYLOAD)

    response = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": {
            "code": "invalid_credentials",
            "message": "The email address or password is invalid.",
        }
    }
