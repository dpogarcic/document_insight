"""Private CLI for provisioning the first evaluation-tenant administrator."""

import argparse
import asyncio
from getpass import getpass
from uuid import UUID

from pydantic import EmailStr, TypeAdapter

from document_insight.application.evaluation.identity import (
    EvaluationIdentityAlreadyProvisionedError,
    EvaluationIdentityProvisioner,
    EvaluationTenantUnavailableError,
)
from document_insight.config import get_settings
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.department.repository import SqlAlchemyDepartmentRepository
from document_insight.infrastructure.security.password_hasher import Argon2PasswordHasher
from document_insight.infrastructure.user.repository import SqlAlchemyUserRepository
from document_insight.infrastructure.user_department.repository import (
    SqlAlchemyUserDepartmentRepository,
)


async def _provision(tenant_id: UUID, email: str, display_name: str, password: str) -> UUID:
    """Run the one-time identity transaction under the restricted auth credential."""
    async with get_session_factory("auth")() as session:
        service = EvaluationIdentityProvisioner(
            SqlAlchemyUserRepository(session),
            SqlAlchemyDepartmentRepository(session),
            SqlAlchemyUserDepartmentRepository(session),
            SqlAlchemyTransactionManager(session),
            Argon2PasswordHasher(),
        )
        return await service.provision(tenant_id, email, display_name, password)


def main() -> None:
    """Read a password from the terminal without passing it through process arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if settings.evaluation_tenant_id is None:
        parser.error("EVALUATION_TENANT_ID must be configured")
    try:
        email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    except ValueError as error:
        parser.error(f"Invalid email address: {error}")
    display_name = args.display_name.strip()
    if not 1 <= len(display_name) <= 100:
        parser.error("Display name must be 1-100 characters")
    password = getpass("New evaluation admin password: ")
    confirmation = getpass("Confirm password: ")
    if not 8 <= len(password) <= 128 or password != confirmation:
        parser.error("Passwords must match and contain 8-128 characters")
    try:
        user_id = asyncio.run(
            _provision(settings.evaluation_tenant_id, email, display_name, password)
        )
    except EvaluationIdentityAlreadyProvisionedError:
        parser.error("The evaluation tenant already has a user; initial provisioning is closed")
    except EvaluationTenantUnavailableError:
        parser.error("The seeded evaluation tenant is unavailable")
    print(f"Created evaluation-tenant admin {user_id} ({email})")


if __name__ == "__main__":
    main()
