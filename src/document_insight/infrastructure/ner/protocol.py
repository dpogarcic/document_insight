"""Protocol for named-entity recognition providers."""

from typing import Protocol

from document_insight.application.configuration.models import NerConfiguration
from document_insight.application.processing.models import NerResult


class NamedEntityRecognizer(Protocol):
    """Detect document language and extract entity mentions from text."""

    def recognize(self, text: str) -> NerResult:
        """Return a typed NER result for supported input text."""


class NamedEntityRecognizerFactory(Protocol):
    """Build a recognizer from the immutable NER profile snapshot."""

    def create(self, configuration: NerConfiguration) -> NamedEntityRecognizer:
        """Return the implementation selected by an explicit NER profile."""
