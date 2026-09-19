"""Expected authentication application errors."""


class EmailAlreadyRegisteredError(Exception):
    """Raised when registration attempts to reuse an existing email address."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials cannot be authenticated."""
