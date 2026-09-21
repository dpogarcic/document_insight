"""Safe errors raised while preparing an authorized retrieval request."""


class QueryProfileUnavailableError(Exception):
    """No active supported query profile is available for the request."""
