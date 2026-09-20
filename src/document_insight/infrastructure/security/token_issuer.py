"""Access-token issuance protocol and JWT adapter."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
from pydantic import SecretStr

from document_insight.application.auth.models import AccessToken, UserCredentials


class TokenIssuer(Protocol):
    """Access-token operations required by login."""

    def issue(self, user: UserCredentials) -> AccessToken:
        """Issue a signed access token for an authenticated user."""


class JwtTokenIssuer(TokenIssuer):
    """Issue signed short-lived JWT access tokens."""

    def __init__(
        self,
        secret_key: SecretStr,
        algorithm: str,
        issuer: str,
        audience: str,
        expire_minutes: int,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._expire_minutes = expire_minutes

    def issue(self, user: UserCredentials) -> AccessToken:
        """Issue a token containing authenticated tenant and department claims."""
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(minutes=self._expire_minutes)
        expires_in = self._expire_minutes * 60
        claims = {
            "sub": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "department_ids": [str(department_id) for department_id in user.department_ids],
            "role": user.role.value,
            "type": "access",
            "iat": issued_at,
            "exp": expires_at,
            "iss": self._issuer,
            "aud": self._audience,
        }
        encoded = jwt.encode(
            claims,
            self._secret_key.get_secret_value(),
            algorithm=self._algorithm,
        )
        return AccessToken(value=encoded, expires_in=expires_in)
