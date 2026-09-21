"""Expected document-library and activation errors."""


class DocumentActivationForbiddenError(Exception):
    """The caller does not hold the tenant-admin activation capability."""


class DocumentVersionNotReadyError(Exception):
    """Only fully processed document versions may be activated."""
