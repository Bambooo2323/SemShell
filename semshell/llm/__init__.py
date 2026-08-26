"""Model-neutral semantic backend interfaces and adapters."""

from semshell.llm.base import (
    LLMBackend,
    LLMRequest,
    LLMResponse,
    SemanticBackend,
    TokenUsage,
)
from semshell.llm.openai import OpenAIResponsesBackend
from semshell.llm.scripted import ScriptedSemanticBackend

__all__ = [
    "LLMBackend",
    "LLMRequest",
    "LLMResponse",
    "OpenAIResponsesBackend",
    "ScriptedSemanticBackend",
    "SemanticBackend",
    "TokenUsage",
]
