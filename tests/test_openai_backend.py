"""Tests for the OpenAI adapter without network access."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openai")

from semshell.llm import LLMRequest
from semshell.llm.openai import OpenAIResponsesBackend


class FakeResponses:
    def __init__(self) -> None:
        self.parameters: dict[str, Any] | None = None

    async def create(self, **parameters: Any) -> Any:
        self.parameters = parameters
        return SimpleNamespace(
            id="resp_test",
            model="test-model",
            output_text="hello",
            status="completed",
            usage=SimpleNamespace(
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
            ),
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_openai_backend_uses_responses_api_and_normalizes_output() -> None:
    client = FakeClient()
    backend = OpenAIResponsesBackend(client=client)

    result = await backend.generate(
        LLMRequest(
            model="test-model",
            input="Say hello",
            instructions="Be brief",
            previous_response_id="resp_previous",
            max_output_tokens=32,
            metadata={"task": "test"},
        )
    )

    assert client.responses.parameters == {
        "model": "test-model",
        "input": "Say hello",
        "instructions": "Be brief",
        "previous_response_id": "resp_previous",
        "max_output_tokens": 32,
        "metadata": {"task": "test"},
    }
    assert result.response_id == "resp_test"
    assert result.output_text == "hello"
    assert result.usage.total_tokens == 6
