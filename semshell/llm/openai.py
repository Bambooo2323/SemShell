"""OpenAI Responses API adapter."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from semshell.llm.base import LLMRequest, LLMResponse, TokenUsage


class OpenAIResponsesBackend:
    """Generate model-neutral results through the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return

        options: dict[str, Any] = {}
        if api_key is not None:
            options["api_key"] = api_key
        if base_url is not None:
            options["base_url"] = base_url
        self._client = AsyncOpenAI(**options)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Create one response and normalize its common fields."""

        parameters: dict[str, Any] = {
            "model": request.model,
            "input": request.input,
        }
        if request.instructions is not None:
            parameters["instructions"] = request.instructions
        if request.previous_response_id is not None:
            parameters["previous_response_id"] = request.previous_response_id
        if request.max_output_tokens is not None:
            parameters["max_output_tokens"] = request.max_output_tokens
        if request.metadata:
            parameters["metadata"] = dict(request.metadata)

        response = await self._client.responses.create(**parameters)
        usage = getattr(response, "usage", None)
        normalized_usage = TokenUsage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
        return LLMResponse(
            response_id=str(response.id),
            model=str(response.model),
            output_text=str(response.output_text),
            status=str(response.status),
            usage=normalized_usage,
            raw=response,
        )
