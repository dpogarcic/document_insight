"""OpenAI-compatible embeddings adapter for any configured endpoint."""

from math import isfinite, sqrt

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from document_insight.application.configuration.models import EmbeddingConfiguration
from document_insight.application.processing.exceptions import EmbeddingError
from document_insight.infrastructure.embedding.protocol import TextEmbedder, TextEmbedderFactory


class _EmbeddingRequest(BaseModel):
    """Validated OpenAI-compatible embedding request payload."""

    model_config = ConfigDict(extra="forbid")

    model: str
    input: tuple[str, ...]


class _EmbeddingResponseItem(BaseModel):
    """One vector returned by an OpenAI-compatible endpoint."""

    model_config = ConfigDict(extra="ignore")

    index: int
    embedding: tuple[float, ...]


class _EmbeddingResponse(BaseModel):
    """Subset of an OpenAI-compatible embeddings response that we consume."""

    model_config = ConfigDict(extra="ignore")

    data: tuple[_EmbeddingResponseItem, ...]


class OpenAICompatibleTextEmbedder(TextEmbedder):
    """Call the configured OpenAI-compatible endpoint without topology assumptions."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def embed(
        self, texts: tuple[str, ...], configuration: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        """Generate, validate, and normalize one vector for every input text."""
        if not texts:
            return ()
        headers = {} if self._api_key is None else {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers=headers,
                    json=_EmbeddingRequest(model=configuration.model, input=texts).model_dump(),
                )
                response.raise_for_status()
            payload = _EmbeddingResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise EmbeddingError from error
        ordered = sorted(payload.data, key=lambda item: item.index)
        if len(ordered) != len(texts) or tuple(item.index for item in ordered) != tuple(
            range(len(texts))
        ):
            raise EmbeddingError
        vectors = tuple(self._validated_vector(item.embedding, configuration) for item in ordered)
        return vectors

    @staticmethod
    def _validated_vector(
        vector: tuple[float, ...], configuration: EmbeddingConfiguration
    ) -> tuple[float, ...]:
        """Reject malformed vectors and apply profile-declared normalization."""
        if len(vector) != configuration.dimensions or not all(isfinite(value) for value in vector):
            raise EmbeddingError
        if not configuration.normalize:
            return vector
        magnitude = sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            raise EmbeddingError
        return tuple(value / magnitude for value in vector)


class OpenAICompatibleTextEmbedderFactory(TextEmbedderFactory):
    """Expose the OpenAI-compatible adapter under its explicit provider key."""

    def __init__(self, base_url: str, api_key: str | None) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def create(self, configuration: EmbeddingConfiguration) -> TextEmbedder:
        """Return an adapter only when the persisted profile selects this protocol."""
        if configuration.provider != "openai_compatible":
            raise ValueError(f"Unsupported embedding provider: {configuration.provider}")
        return OpenAICompatibleTextEmbedder(self._base_url, self._api_key)
