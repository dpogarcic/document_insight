"""Commands accepted by the local-authentication application service."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    """Validated data used to provision a new tenant administrator."""

    email: str
    password: str
    display_name: str
    tenant_name: str
