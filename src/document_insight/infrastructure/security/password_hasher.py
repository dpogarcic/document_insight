"""Password hashing protocol and Argon2 adapter."""

from typing import Protocol

from pwdlib import PasswordHash


class PasswordHasher(Protocol):
    """Password hashing operations required by local authentication."""

    def hash(self, password: str) -> str:
        """Create a password hash suitable for persistent storage."""

    def verify(self, password: str, password_hash: str) -> bool:
        """Verify a password against a stored hash."""

    def verify_unknown_user(self, password: str) -> None:
        """Perform equivalent work when the requested user does not exist."""


class Argon2PasswordHasher(PasswordHasher):
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
