"""Protocol for named-entity recognition providers."""

from typing import Protocol

from document_insight.application.processing.models import NerResult


class NamedEntityRecognizer(Protocol):
    """Detect document language and extract entity mentions from text."""

    def recognize(self, text: str) -> NerResult:
        """Return a typed NER result for supported input text."""
