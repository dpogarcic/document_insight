"""Expected processing-job query errors."""


class JobNotFoundError(Exception):
    """The requested job does not exist within the caller's authorization scope."""
