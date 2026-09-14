"""Immutable events delivered to process activations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from semshell.kernel.process import ProcessError, ProcessResult
from semshell.resources.types import ResourceBindingId, ResourceInvocationId
from semshell.security.principal import Principal
from semshell.software.image import ProcessImageDescriptor


@dataclass(frozen=True, slots=True)
class Message:
    """Structured, at-most-once in-memory IPC payload."""

    source_pid: int
    target_pid: int
    payload: Any

    def __post_init__(self) -> None:
        if self.source_pid <= 0 or self.target_pid <= 0:
            raise ValueError("message PIDs must be positive")


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


@dataclass(frozen=True, slots=True)
class ResourceCompleted:
    """Continuation for one successfully committed Host resource invocation."""

    invocation_id: ResourceInvocationId
    binding_id: ResourceBindingId
    operation: str
    value: Any

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("resource operation must not be empty")


@dataclass(frozen=True, slots=True)
class ResourceRejected:
    """Continuation for one rejected or failed Host resource invocation."""

    invocation_id: ResourceInvocationId
    binding_id: ResourceBindingId
    operation: str
    error: ProcessError

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("resource operation must not be empty")


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
    | ResourceCompleted
    | ResourceRejected
)
