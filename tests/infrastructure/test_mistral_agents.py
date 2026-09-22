"""Tests for the Mistral OpenAI Agents SDK boundary."""

import asyncio

from agents import Agent
from pydantic import BaseModel

from document_insight.infrastructure.mistral.agents import MistralStructuredAgentClient


class _Answer(BaseModel):
    answer: str


class _Result:
    def __init__(self, value: _Answer) -> None:
        self.final_output = value


class _RateLimitedError(Exception):
    status_code = 429


def test_complete_uses_a_typed_chat_agent_without_a_network_call() -> None:
    """The adapter passes the profile's model and output controls to the SDK."""
    observed_agent: Agent[None] | None = None

    async def fake_runner(agent: Agent[None], input_text: str) -> object:
        nonlocal observed_agent
        observed_agent = agent
        assert input_text == "authorized passages"
        return _Result(_Answer(answer="Grounded response"))

    client = MistralStructuredAgentClient(
        "https://api.mistral.ai/v1",
        "test-mistral-key",
        runner=fake_runner,
    )

    result = asyncio.run(
        client.complete(
            name="Test agent",
            instructions="Use evidence only.",
            input_text="authorized passages",
            model_name="ministral-3b-2512",
            output_type=_Answer,
            temperature=0.0,
            max_output_tokens=128,
        )
    )

    assert result == _Answer(answer="Grounded response")
    assert observed_agent is not None
    assert observed_agent.model is not None


def test_complete_retries_a_mistral_rate_limit() -> None:
    """The adapter waits before retrying the account's one-request-per-second limit."""
    attempts = 0
    delays: list[float] = []

    async def fake_runner(_: Agent[None], __: str) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _RateLimitedError()
        return _Result(_Answer(answer="Grounded response"))

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    client = MistralStructuredAgentClient(
        "https://api.mistral.ai/v1",
        "test-mistral-key",
        runner=fake_runner,
        sleep=fake_sleep,
    )

    result = asyncio.run(
        client.complete(
            name="Test agent",
            instructions="Use evidence only.",
            input_text="authorized passages",
            model_name="ministral-3b-2512",
            output_type=_Answer,
            temperature=0.0,
            max_output_tokens=128,
        )
    )

    assert result == _Answer(answer="Grounded response")
    assert attempts == 2
    assert delays == [5.0]
