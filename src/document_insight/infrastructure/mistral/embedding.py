"""Mistral embeddings adapter with profile-bound vector validation."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from math import isfinite, sqrt

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from document_insight.application.configuration.models import EmbeddingConfiguration
from document_insight.application.processing.exceptions import EmbeddingError
from document_insight.infrastructure.embedding.protocol import TextEmbedder, TextEmbedderFactory
from document_insight.infrastructure.mistral.rate_limit import (
    MAX_RATE_LIMIT_ATTEMPTS,
    retry_delay_seconds,
)

Sleep = Callable[[float], Awaitable[None]]

logger = logging.getLogger(__name__)


class _EmbeddingRequest(BaseModel):
    """Validated Mistral embeddings request payload."""

    model_config = ConfigDict(extra="forbid")

    model: str
    input: tuple[str, ...]


class _EmbeddingResponseItem(BaseModel):
    """One vector returned by the Mistral embeddings API."""

    model_config = ConfigDict(extra="ignore")

    index: int
    embedding: tuple[float, ...]


class _EmbeddingResponse(BaseModel):
    """Subset of a Mistral embeddings response consumed by this adapter."""

    model_config = ConfigDict(extra="ignore")

    data: tuple[_EmbeddingResponseItem, ...]


class MistralTextEmbedder(TextEmbedder):
    """Generate Mistral vectors without exposing document text in errors or logs."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep

    async def embed(
        self, texts: tuple[str, ...], configuration: EmbeddingConfiguration
    ) -> tuple[tuple[float, ...], ...]:
        """Generate profile-compatible vectors for the supplied text batch."""
        if not texts:
            return ()
        try:
            for attempt in range(MAX_RATE_LIMIT_ATTEMPTS):
                async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
                    response = await client.post(
                        f"{self._base_url}/embeddings",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=_EmbeddingRequest(model=configuration.model, input=texts).model_dump(),
                    )
                if response.status_code == 429 and attempt + 1 < MAX_RATE_LIMIT_ATTEMPTS:
                    delay = retry_delay_seconds(attempt)
                    logger.info(
                        "Mistral embedding rate limit retry: model=%s attempt=%s delay_seconds=%.1f",
                        configuration.model,
                        attempt + 1,
                        delay,
                    )
                    await self._sleep(delay)
                    continue
                response.raise_for_status()
                break
            payload = _EmbeddingResponse.model_validate(response.json())
        except httpx.HTTPStatusError as error:
            raise EmbeddingError(f"provider_rejected_http_{error.response.status_code}") from error
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            raise EmbeddingError("provider_response_invalid") from error
        ordered = tuple(sorted(payload.data, key=lambda item: item.index))
        if len(ordered) != len(texts) or tuple(item.index for item in ordered) != tuple(
            range(len(texts))
        ):
            raise EmbeddingError("response_incomplete_or_malformed")
        return tuple(self._validated_vector(item.embedding, configuration) for item in ordered)

    @staticmethod
    def _validated_vector(
        vector: tuple[float, ...], configuration: EmbeddingConfiguration
    ) -> tuple[float, ...]:
        """Reject malformed vectors and apply profile-declared normalization."""
        if len(vector) != configuration.dimensions:
            raise EmbeddingError("vector_dimension_mismatch")
        if not all(isfinite(value) for value in vector):
            raise EmbeddingError("vector_contains_non_finite_values")
        if not configuration.normalize:
            return vector
        magnitude = sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            raise EmbeddingError("vector_is_zero")
        return tuple(value / magnitude for value in vector)


class MistralTextEmbedderFactory(TextEmbedderFactory):
    """Create the explicit Mistral embedding adapter selected by a profile."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def create(self, configuration: EmbeddingConfiguration) -> TextEmbedder:
        """Return Mistral only for profiles that explicitly select it."""
        if configuration.provider != "mistral":
            raise ValueError(f"Unsupported embedding provider: {configuration.provider}")
        return MistralTextEmbedder(self._base_url, self._api_key)
