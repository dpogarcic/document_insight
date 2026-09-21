"""Contract tests for the OpenAI-compatible embeddings adapter."""

import asyncio
import json

import httpx

from document_insight.application.configuration.models import EmbeddingConfiguration
from document_insight.application.processing.exceptions import EmbeddingError
from document_insight.infrastructure.embedding.openai_compatible import (
    OpenAICompatibleTextEmbedder,
)


def embedding_configuration() -> EmbeddingConfiguration:
    """Return the minimal immutable configuration for the test adapter."""
    return EmbeddingConfiguration(
        provider="openai_compatible",
        model="test-embedding-model",
        configuration_revision="1",
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
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]},
        )

    embedder = OpenAICompatibleTextEmbedder(
        "http://model-runner/engines/v1/",
        "local-token",
        httpx.MockTransport(handler),
    )

    result = asyncio.run(embedder.embed(("A document passage",), embedding_configuration()))

    assert result == ((0.6, 0.8),)
    assert observed_request is not None
    assert observed_request.url == httpx.URL("http://model-runner/engines/v1/embeddings")
    assert observed_request.headers["Authorization"] == "Bearer local-token"
    assert json.loads(observed_request.content) == {
        "model": "test-embedding-model",
        "input": ["A document passage"],
    }


def test_embed_rejects_a_vector_with_the_wrong_profile_dimension() -> None:
    """A provider response cannot silently violate the persisted profile."""
    embedder = OpenAICompatibleTextEmbedder(
        "http://model-runner/engines/v1",
        None,
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        ),
    )

    try:
        asyncio.run(embedder.embed(("A document passage",), embedding_configuration()))
    except EmbeddingError:
        pass
    else:
        raise AssertionError("Expected an embedding dimension mismatch to be rejected")
