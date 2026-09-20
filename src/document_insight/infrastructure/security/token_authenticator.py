"""Access-token authentication protocol and JWT adapter."""

from typing import Protocol
from uuid import UUID

import jwt
from pydantic import SecretStr

from document_insight.application.auth.models import AuthorizationContext, UserRole


class TokenAuthenticator(Protocol):
    """Translate a validated bearer token into trusted authorization claims."""

    def authenticate(self, token: str) -> AuthorizationContext:
        """Return trusted claims or raise when the token is invalid."""


class JwtTokenAuthenticator(TokenAuthenticator):
    """Validate signed JWT access tokens and translate their claims."""

    def __init__(
        self,
        secret_key: SecretStr,
        algorithm: str,
        issuer: str,
        audience: str,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience

    def authenticate(self, token: str) -> AuthorizationContext:
        """Decode a valid access token or propagate PyJWT's validation error."""
        claims = jwt.decode(
            token,
            self._secret_key.get_secret_value(),
            algorithms=[self._algorithm],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["sub", "tenant_id", "department_ids", "role", "type"]},
        )
        if claims["type"] != "access":
            raise jwt.InvalidTokenError("Token is not an access token")

        department_ids = claims["department_ids"]
        if not isinstance(department_ids, list) or not department_ids:
            raise jwt.InvalidTokenError("Token has no department scope")

        try:
            return AuthorizationContext(
                user_id=UUID(claims["sub"]),
                tenant_id=UUID(claims["tenant_id"]),
                department_ids=tuple(UUID(value) for value in department_ids),
                role=UserRole(claims["role"]),
            )
        except (TypeError, ValueError) as error:
            raise jwt.InvalidTokenError("Token authorization claims are invalid") from error
