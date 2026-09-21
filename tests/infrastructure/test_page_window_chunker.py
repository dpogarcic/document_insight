"""Tests for deterministic, citation-ready text chunking."""

from document_insight.infrastructure.document_chunker.page_window import PageWindowDocumentChunker


def test_chunker_preserves_page_boundaries_and_source_offsets() -> None:
    """Chunks are ordered, page-local, and point back to their exact source text."""
    text = "alpha beta gamma delta\f epsilon zeta eta theta"

    chunks = PageWindowDocumentChunker(max_chars=12, overlap_chars=3).chunk(text)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(text[chunk.start_offset : chunk.end_offset] == chunk.text for chunk in chunks)
    assert all("\f" not in chunk.text for chunk in chunks)
    assert all(len(chunk.text) <= 12 for chunk in chunks)


def test_chunker_keeps_overlap_on_word_boundaries() -> None:
    """Adjacent windows retain context without splitting a word at their starts."""
    chunks = PageWindowDocumentChunker(max_chars=13, overlap_chars=4).chunk(
        "alpha bravo charlie delta"
    )

    assert [chunk.text for chunk in chunks] == ["alpha bravo", "bravo charlie", "charlie delta"]
