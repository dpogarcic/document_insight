"""Protocol for immutable document parsing adapters."""

from typing import Protocol

from document_insight.application.processing.models import ParsedDocument


class DocumentParser(Protocol):
    """Extract plain text from one immutable original's bytes."""

    def parse(self, content: bytes) -> ParsedDocument:
        """Return version-scoped parsed text or raise a safe parsing error."""
