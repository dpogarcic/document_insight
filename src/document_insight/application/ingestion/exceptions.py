"""Expected ingestion errors translated at the HTTP boundary."""


class IngestionError(Exception):
    """Base class for safe, expected ingestion failures."""


class UnsupportedDocumentTypeError(IngestionError):
    """The MIME type or file signature is unsupported or inconsistent."""


class EmptyDocumentError(IngestionError):
    """The uploaded document contains no bytes."""


class DocumentTooLargeError(IngestionError):
    """The upload exceeds the configured maximum size."""


class DocumentNotFoundError(IngestionError):
    """The requested logical document does not exist in the actor's tenant."""


class IngestionForbiddenError(IngestionError):
    """The actor cannot upload or version the requested document."""


class InvalidDepartmentScopeError(IngestionError):
    """A requested department is outside the actor's tenant or authority."""


class ObjectStorageUnavailableError(IngestionError):
    """The original could not be durably written to object storage."""
