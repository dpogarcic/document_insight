"""Protocol for deterministic citation-ready document chunking."""

from typing import Protocol

from document_insight.application.configuration.models import ChunkingConfiguration
from document_insight.application.processing.models import DocumentChunk


class DocumentChunker(Protocol):
    """Split extracted text into ordered, page-scoped passages."""

    name: str
    version: str

    def chunk(self, text: str) -> tuple[DocumentChunk, ...]:
        """Return deterministic chunks with original-text offsets and page numbers."""


class DocumentChunkerFactory(Protocol):
    """Build the explicit chunker selected by an immutable profile."""

    def create(self, configuration: ChunkingConfiguration) -> DocumentChunker:
        """Return a supported chunker for one validated configuration snapshot."""
