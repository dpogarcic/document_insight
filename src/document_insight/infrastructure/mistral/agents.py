"""Typed OpenAI Agents SDK boundary for Mistral chat completions."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from pydantic import BaseModel

from document_insight.application.query.exceptions import QueryProviderUnavailableError
from document_insight.infrastructure.mistral.rate_limit import (
    MAX_RATE_LIMIT_ATTEMPTS,
    retry_delay_seconds,
)

Output = TypeVar("Output", bound=BaseModel)
RunAgent = Callable[[Agent[None], str], Awaitable[object]]
Sleep = Callable[[float], Awaitable[None]]

logger = logging.getLogger(__name__)


class MistralStructuredAgentClient:
    """Run one typed Mistral chat completion with tracing permanently disabled."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        runner: RunAgent | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        # Document passages and questions must never be exported by SDK tracing.
        set_tracing_disabled(disabled=True)
        self._client = AsyncOpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
        self._runner = runner or self._run
        self._sleep = sleep

    async def complete(
        self,
        *,
        name: str,
        instructions: str,
        input_text: str,
        model_name: str,
        output_type: type[Output],
        temperature: float,
        max_output_tokens: int,
    ) -> Output:
        """Return validated structured output without logging the prompt or response body."""
        agent = Agent(
            name=name,
            instructions=instructions,
            model=OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=self._client,
            ),
            model_settings=ModelSettings(
                temperature=temperature,
                max_tokens=max_output_tokens,
            ),
            output_type=output_type,
        )
        for attempt in range(MAX_RATE_LIMIT_ATTEMPTS):
            try:
                result = await self._runner(agent, input_text)
                break
            except Exception as error:
                if (
                    getattr(error, "status_code", None) == 429
                    and attempt + 1 < MAX_RATE_LIMIT_ATTEMPTS
                ):
                    delay = retry_delay_seconds(attempt)
                    logger.info(
                        "provider request retry scheduled",
                        extra={
                            "operation": "provider_request",
                            "stage": "completion",
                            "outcome": "retry_scheduled",
                            "error_code": "rate_limited",
                            "provider": "mistral",
                        },
                    )
                    await self._sleep(delay)
                    continue
                logger.warning(
                    "provider request failed",
                    extra={
                        "operation": "provider_request",
                        "stage": "completion",
                        "outcome": "error",
                        "error_code": "provider_unavailable",
                        "provider": "mistral",
                    },
                )
                raise QueryProviderUnavailableError from error
        output = getattr(result, "final_output", None)
        if not isinstance(output, output_type):
            raise QueryProviderUnavailableError
        return output

    @staticmethod
    async def _run(agent: Agent[None], input_text: str) -> object:
        """Invoke the SDK's non-streaming run loop."""
        return await Runner.run(agent, input_text)
