"""Deterministic page-aware text window chunker."""

from document_insight.application.configuration.models import ChunkingConfiguration
from document_insight.application.processing.models import DocumentChunk
from document_insight.infrastructure.document_chunker.protocol import (
    DocumentChunker,
    DocumentChunkerFactory,
)


class PageWindowDocumentChunker(DocumentChunker):
    """Keep citations page-local while preferring whitespace boundaries."""

    name = "page_window"
    version = "1"

    def __init__(self, max_chars: int, overlap_chars: int) -> None:
        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    def chunk(self, text: str) -> tuple[DocumentChunk, ...]:
        """Chunk each form-feed-delimited page without crossing page boundaries."""
        chunks: list[DocumentChunk] = []
        page_start = 0
        for page_number, raw_page in enumerate(text.split("\f"), start=1):
            leading = len(raw_page) - len(raw_page.lstrip())
            page = raw_page.strip()
            if page:
                chunks.extend(
                    self._chunk_page(page, page_start + leading, page_number, len(chunks))
                )
            page_start += len(raw_page) + 1
        return tuple(chunks)

    def _chunk_page(
        self, page: str, page_start: int, page_number: int, ordinal_start: int
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        start = 0
        while start < len(page):
            end = min(start + self._max_chars, len(page))
            if end < len(page):
                end = self._preferred_break(page, start, end)
            raw_chunk = page[start:end]
            leading = len(raw_chunk) - len(raw_chunk.lstrip())
            chunk_text = raw_chunk.strip()
            if chunk_text:
                chunk_start = start + leading
                chunks.append(
                    DocumentChunk(
                        ordinal=ordinal_start + len(chunks),
                        text=chunk_text,
                        start_offset=page_start + chunk_start,
                        end_offset=page_start + chunk_start + len(chunk_text),
                        page_number=page_number,
                    )
                )
            if end == len(page):
                break
            start = self._next_start(page, start, end)
        return chunks

    def _next_start(self, text: str, current_start: int, end: int) -> int:
        """Retain overlap while beginning the next window at a word boundary."""
        candidate = max(end - self._overlap_chars, current_start + 1)
        while candidate > current_start + 1 and not text[candidate - 1].isspace():
            candidate -= 1
        return candidate

    @staticmethod
    def _preferred_break(text: str, start: int, end: int) -> int:
        """Use a nearby whitespace boundary, falling back to the maximum window size."""
        minimum = start + (end - start) // 2
        for index in range(end, minimum, -1):
            if text[index - 1].isspace():
                return index
        return end


class PageWindowDocumentChunkerFactory(DocumentChunkerFactory):
    """Build the local page-window chunker from an immutable profile snapshot."""

    def create(self, configuration: ChunkingConfiguration) -> DocumentChunker:
        """Reject unknown configuration instead of silently applying runtime defaults."""
        if (
            configuration.implementation != PageWindowDocumentChunker.name
            or configuration.implementation_revision != PageWindowDocumentChunker.version
        ):
            raise ValueError("unsupported chunking profile")
        return PageWindowDocumentChunker(configuration.max_chars, configuration.overlap_chars)
