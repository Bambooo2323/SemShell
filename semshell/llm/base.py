"""Model-neutral interface for one semantic model request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Provider-neutral input for one model response."""

    model: str
    input: Any
    instructions: str | None = None
    previous_response_id: str | None = None
    max_output_tokens: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model must not be empty")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized token accounting returned by a backend."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Provider-neutral output from one model response."""

    response_id: str
    model: str
    output_text: str
    status: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Any = None


class SemanticBackend(Protocol):
    """Provider-neutral backend capable of one semantic decision."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one response without defining an agent loop."""
        ...


LLMBackend = SemanticBackend
