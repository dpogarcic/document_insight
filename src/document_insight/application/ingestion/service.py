"""Application workflow for validating and storing document originals."""

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from document_insight.application.ingestion.contracts import (
    DocumentRepository,
    IngestDocumentCommand,
    OriginalObjectStorage,
    StoreDocumentVersion,
)
from document_insight.application.ingestion.exceptions import (
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionForbiddenError,
    UnsupportedDocumentTypeError,
)
from document_insight.domain.auth import UserRole
from document_insight.domain.ingestion import StoredDocumentVersion, StoredMediaType

_SIGNATURES = {
    StoredMediaType.PDF: (b"%PDF-", ".pdf"),
    StoredMediaType.PNG: (b"\x89PNG\r\n\x1a\n", ".png"),
    StoredMediaType.JPEG: (b"\xff\xd8\xff", ".jpg"),
}


class IngestionService:
    """Validate, authorize, and persist an immutable original document."""

    def __init__(
        self,
        repository: DocumentRepository,
        object_storage: OriginalObjectStorage,
        max_upload_bytes: int,
    ) -> None:
        self._repository = repository
        self._object_storage = object_storage
        self._max_upload_bytes = max_upload_bytes

    async def ingest(self, command: IngestDocumentCommand) -> StoredDocumentVersion:
        """Store an upload and persist its metadata, compensating on database failure."""
        if command.actor.role is UserRole.VIEWER:
            raise IngestionForbiddenError
        if not command.content:
            raise EmptyDocumentError
        if len(command.content) > self._max_upload_bytes:
            raise DocumentTooLargeError

        media_type, suffix = self._detect_media_type(
            command.content,
            command.declared_content_type,
        )
        effective_departments = await self._repository.validate_upload_target(
            command.document_id,
            command.department_ids,
            command.actor,
        )

        document_id = command.document_id or uuid4()
        version_id = uuid4()
        object_key = (
            f"tenants/{command.actor.tenant_id}/documents/{document_id}/"
            f"versions/{version_id}/original{suffix}"
        )
        await self._object_storage.put(object_key, command.content, media_type.value)

        upload = StoreDocumentVersion(
            document_id=document_id,
            document_version_id=version_id,
            filename=Path(command.filename).name or f"document{suffix}",
            object_key=object_key,
            media_type=media_type,
            size_bytes=len(command.content),
            content_sha256=sha256(command.content).hexdigest(),
            requested_department_ids=command.department_ids,
            actor=command.actor,
            replaces_existing_document=command.document_id is not None,
        )
        try:
            return await self._repository.create_stored_version(upload, effective_departments)
        except Exception:
            await self._object_storage.delete(object_key)
            raise

    @staticmethod
    def _detect_media_type(
        content: bytes, declared_content_type: str | None
    ) -> tuple[StoredMediaType, str]:
        for media_type, (signature, suffix) in _SIGNATURES.items():
            if content.startswith(signature):
                if declared_content_type not in {None, "", media_type.value}:
                    raise UnsupportedDocumentTypeError
                return media_type, suffix
        raise UnsupportedDocumentTypeError
