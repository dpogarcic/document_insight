"""Safe processing errors for worker failure classification."""


class ParsingError(Exception):
    """The original cannot be parsed into usable text."""


class UnsupportedProcessingMediaTypeError(ParsingError):
    """No parser is configured for the stored media type."""


class NerError(Exception):
    """The configured NER provider could not safely process extracted text."""
