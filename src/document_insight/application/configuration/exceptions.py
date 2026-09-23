"""Safe application errors for configuration-profile resolution."""


class ProcessingProfileUnavailableError(Exception):
    """No active immutable ingestion profile is available for a new job."""


class InvalidProcessingProfileError(Exception):
    """A persisted profile cannot be resolved as a supported configuration."""


class InvalidProfileProposalError(Exception):
    """A proposed profile is missing, incompatible, or unsupported."""


class ProfileRevisionConflictError(Exception):
    """The active pointer changed since the operator reviewed it."""
