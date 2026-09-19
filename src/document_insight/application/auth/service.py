"""Local registration and login orchestration."""

import asyncio

from document_insight.application.auth.contracts import (
    AuthRepository,
    PasswordHasher,
    RegisterUserCommand,
    TokenIssuer,
)
from document_insight.application.auth.exceptions import InvalidCredentialsError
from document_insight.domain.auth import AccessToken, RegisteredUser


class AuthService:
    """Coordinate registration and login without depending on framework or vendor SDKs."""

    def __init__(
        self,
        repository: AuthRepository,
        password_hasher: PasswordHasher,
        token_issuer: TokenIssuer,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_issuer = token_issuer

    async def register(self, command: RegisterUserCommand) -> RegisteredUser:
        """Hash credentials and provision a new tenant administrator."""
        password_hash = await asyncio.to_thread(self._password_hasher.hash, command.password)
        return await self._repository.create_tenant_admin(command, password_hash)

    async def login(self, email: str, password: str) -> AccessToken:
        """Authenticate credentials and issue a short-lived access token."""
        normalized_email = email.strip().lower()
        user = await self._repository.get_user_by_email(normalized_email)
        if user is None:
            await asyncio.to_thread(self._password_hasher.verify_unknown_user, password)
            raise InvalidCredentialsError

        is_valid = await asyncio.to_thread(
            self._password_hasher.verify,
            password,
            user.password_hash,
        )
        if not is_valid:
            raise InvalidCredentialsError

        return self._token_issuer.issue(user)
