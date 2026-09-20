"""Original-file object-storage protocol."""

from typing import Protocol


class OriginalObjectStorage(Protocol):
    """Immutable original-file storage operations required by ingestion."""

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store one original object at a unique key."""

    async def delete(self, key: str) -> None:
        """Delete an object while compensating for a failed metadata write."""
