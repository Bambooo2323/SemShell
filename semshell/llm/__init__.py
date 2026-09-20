"""Model-neutral semantic backend interfaces and offline adapters."""

from semshell.llm.base import (
    LLMBackend,
    LLMRequest,
    LLMResponse,
    SemanticBackend,
    TokenUsage,
)
from semshell.llm.scripted import ScriptedSemanticBackend

__all__ = [
    "LLMBackend",
    "LLMRequest",
    "LLMResponse",
    "ScriptedSemanticBackend",
    "SemanticBackend",
    "TokenUsage",
]
