"""Provider protocol for generating profile-compatible text embeddings."""

from typing import Protocol

from document_insight.application.configuration.models import EmbeddingConfiguration


class TextEmbedder(Protocol):
    """Generate vectors for text using one immutable embedding configuration."""

    async def embed(
        self, texts: tuple[str, ...], configuration: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        """Return one validated vector per input text in the original order."""


class TextEmbedderFactory(Protocol):
    """Select a deployed adapter from a profile's explicit provider key."""

    def create(self, configuration: EmbeddingConfiguration) -> TextEmbedder:
        """Return the adapter for a supported embedding provider."""
