"""Immutable events delivered to process activations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias
from uuid import uuid4

from semshell.kernel.process import ProcessError, ProcessResult
from semshell.security.principal import Principal
from semshell.software.image import ProcessImageDescriptor


class MessageKind(StrEnum):
    """Kernel-defined IPC message categories."""

    REQUEST = "REQUEST"
    RESULT = "RESULT"
    EVENT = "EVENT"
    ERROR = "ERROR"
    SIGNAL = "SIGNAL"


@dataclass(frozen=True, slots=True)
class Message:
    """Structured, at-most-once in-memory IPC payload."""

    source_pid: int
    target_pid: int
    kind: MessageKind
    payload: Any
    message_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_pid <= 0 or self.target_pid <= 0:
            raise ValueError("message PIDs must be positive")
        if not self.message_id:
            raise ValueError("message ID must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class Started:
    """Initial event queued when a process is admitted."""


@dataclass(frozen=True, slots=True)
class MessageReceived:
    """Event wrapping an accepted IPC message."""

    message: Message


@dataclass(frozen=True, slots=True)
class ChildrenCompleted:
    """Single completion event emitted for one satisfied wait registration."""

    results: tuple[ProcessResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))


@dataclass(frozen=True, slots=True)
class Spawned:
    """Continuation event for a successful non-waiting Spawn."""

    pids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.pids:
            raise ValueError("Spawned requires at least one PID")
        object.__setattr__(self, "pids", tuple(self.pids))


@dataclass(frozen=True, slots=True)
class OperationCompleted:
    """Continuation event for a completed control operation."""

    operation: str
    target_pids: tuple[int, ...] = ()
    result: Any = None

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("operation name must not be empty")
        object.__setattr__(self, "target_pids", tuple(self.target_pids))


@dataclass(frozen=True, slots=True)
class OperationRejected:
    """Continuation event for a well-formed operation that was rejected."""

    operation: str
    error: ProcessError

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("operation name must not be empty")


@dataclass(frozen=True, slots=True)
class ContinuationEvent:
    """Explicit user-space continuation requested by Yield."""

    payload: Any = None


@dataclass(frozen=True, slots=True)
class ConsoleInput:
    """Input delivered by a console bridge bound to this Process."""

    principal: Principal
    payload: Any


@dataclass(frozen=True, slots=True)
class ImagesDiscovered:
    """Factory-free Catalog snapshot returned to a user-space Process."""

    images: tuple[ProcessImageDescriptor, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))


ProcessEvent: TypeAlias = (
    Started
    | MessageReceived
    | ChildrenCompleted
    | Spawned
    | OperationCompleted
    | OperationRejected
    | ContinuationEvent
    | ConsoleInput
    | ImagesDiscovered
)
