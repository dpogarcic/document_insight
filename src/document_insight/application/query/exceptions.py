"""Safe errors raised while preparing an authorized retrieval request."""


class QueryProfileUnavailableError(Exception):
    """No active supported query profile is available for the request."""


class QueryProviderUnavailableError(Exception):
    """A configured retrieval, reranking, or generation provider could not serve a query."""


class InvalidGroundingError(Exception):
    """The provider could not attach an answer to the supplied evidence passages."""
