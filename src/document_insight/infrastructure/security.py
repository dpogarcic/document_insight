"""Password hashing and JWT adapters for local authentication."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pydantic import SecretStr

from document_insight.domain.auth import AccessToken, AuthenticatedUser, StoredUser, UserRole


class Argon2PasswordHasher:
    """Hash passwords with pwdlib's recommended Argon2 configuration."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()
        self._unknown_user_hash = self._password_hash.hash("unknown-user-password")

    def hash(self, password: str) -> str:
        """Create an Argon2 password hash."""
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        """Verify a password against an Argon2 hash."""
        return self._password_hash.verify(password, password_hash)

    def verify_unknown_user(self, password: str) -> None:
        """Reduce user-enumeration timing differences for unknown email addresses."""
        self._password_hash.verify(password, self._unknown_user_hash)


class JwtTokenIssuer:
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

    def issue(self, user: StoredUser) -> AccessToken:
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


class JwtTokenAuthenticator:
    """Validate signed access tokens and translate their claims into an identity."""

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

    def authenticate(self, token: str) -> AuthenticatedUser:
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
            return AuthenticatedUser(
                user_id=UUID(claims["sub"]),
                tenant_id=UUID(claims["tenant_id"]),
                department_ids=tuple(UUID(value) for value in department_ids),
                role=UserRole(claims["role"]),
            )
        except (TypeError, ValueError) as error:
            raise jwt.InvalidTokenError("Token authorization claims are invalid") from error
