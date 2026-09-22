"""Contract tests for the Mistral embeddings adapter."""

import asyncio
import json

import httpx

from document_insight.application.configuration.models import EmbeddingConfiguration
from document_insight.application.processing.exceptions import EmbeddingError
from document_insight.infrastructure.mistral.embedding import MistralTextEmbedder


def embedding_configuration() -> EmbeddingConfiguration:
    """Return the immutable Mistral profile used by these tests."""
    return EmbeddingConfiguration(
        provider="mistral",
        model="mistral-embed",
        configuration_revision="mistral-embed-2023-12",
        dimensions=2,
        normalize=True,
        batch_size=32,
    )


def test_embed_posts_profile_model_and_normalizes_vectors() -> None:
    """The provider request and returned vector are both profile-bound."""
    observed_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_request
        observed_request = request
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]})

    embedder = MistralTextEmbedder(
        "https://api.mistral.ai/v1/",
        "test-token",
        httpx.MockTransport(handler),
    )

    result = asyncio.run(embedder.embed(("A document passage",), embedding_configuration()))

    assert result == ((0.6, 0.8),)
    assert observed_request is not None
    assert observed_request.url == httpx.URL("https://api.mistral.ai/v1/embeddings")
    assert observed_request.headers["Authorization"] == "Bearer test-token"
    assert json.loads(observed_request.content) == {
        "model": "mistral-embed",
        "input": ["A document passage"],
    }


def test_embed_rejects_a_vector_with_the_wrong_profile_dimension() -> None:
    """A provider response cannot silently violate the persisted profile."""
    embedder = MistralTextEmbedder(
        "https://api.mistral.ai/v1",
        "test-token",
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        ),
    )

    try:
        asyncio.run(embedder.embed(("A document passage",), embedding_configuration()))
    except EmbeddingError as error:
        assert str(error) == "vector_dimension_mismatch"
    else:
        raise AssertionError("Expected an embedding dimension mismatch to be rejected")


def test_embed_retries_a_mistral_rate_limit() -> None:
    """The first RAG call waits for the provider's slower free-tier window."""
    requests = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]})

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    embedder = MistralTextEmbedder(
        "https://api.mistral.ai/v1",
        "test-token",
        httpx.MockTransport(handler),
        sleep=fake_sleep,
    )

    result = asyncio.run(embedder.embed(("A document passage",), embedding_configuration()))

    assert result == ((0.6, 0.8),)
    assert requests == 2
    assert delays == [5.0]
