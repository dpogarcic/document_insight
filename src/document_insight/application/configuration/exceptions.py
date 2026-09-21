"""Safe application errors for configuration-profile resolution."""


class ProcessingProfileUnavailableError(Exception):
    """No active immutable ingestion profile is available for a new job."""


class InvalidProcessingProfileError(Exception):
    """A persisted profile cannot be resolved as a supported configuration."""
