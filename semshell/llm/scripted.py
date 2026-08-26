"""Deterministic semantic backend for offline tests and demonstrations."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from semshell.llm.base import LLMRequest, LLMResponse


class ScriptedSemanticBackend:
    """Return predefined output texts without network or model access."""

    def __init__(self, outputs: Iterable[str]) -> None:
        self._outputs = deque(outputs)
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._outputs:
            raise RuntimeError("scripted semantic backend has no remaining output")
        return LLMResponse(
            response_id=f"scripted-{len(self.requests)}",
            model=request.model,
            output_text=self._outputs.popleft(),
            status="completed",
        )
