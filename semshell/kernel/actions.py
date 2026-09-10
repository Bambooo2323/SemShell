"""Immutable actions returned by process programs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from semshell.kernel.events import ContinuationEvent, MessageKind
from semshell.kernel.process import CancelMode, ProcessError, WaitMode
from semshell.resources.types import ResourceBindingId
from semshell.software.image import ProcessSpec


@dataclass(frozen=True, slots=True)
class Send:
    """Send one message with source identity supplied by the Kernel."""

    target_pid: int
    payload: Any
    kind: MessageKind = MessageKind.EVENT
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.target_pid <= 0:
            raise ValueError("target PID must be positive")


@dataclass(frozen=True, slots=True)
class Cancel:
    """Request cancellation from one authenticated guest Process."""

    target_pid: int
    mode: CancelMode = CancelMode.SELF
    reason: str = "cancelled"

    def __post_init__(self) -> None:
        if self.target_pid <= 0:
            raise ValueError("target PID must be positive")
        if not self.reason:
            raise ValueError("cancellation reason must not be empty")


@dataclass(frozen=True, slots=True)
class Detach:
    """Remove lifecycle ownership from one direct attached child."""

    child_pid: int

    def __post_init__(self) -> None:
        if self.child_pid <= 0:
            raise ValueError("child PID must be positive")


@dataclass(frozen=True, slots=True)
class Spawn:
    """Request atomic admission of one or more process specifications."""

    specs: tuple[ProcessSpec, ...]
    wait: bool = False
    wait_mode: WaitMode = WaitMode.ALL

    def __post_init__(self) -> None:
        if not self.specs:
            raise ValueError("Spawn requires at least one process specification")
        object.__setattr__(self, "specs", tuple(self.specs))


@dataclass(frozen=True, slots=True)
class Wait:
    """Wait for direct attached children under the selected mode."""

    child_pids: tuple[int, ...] = ()
    mode: WaitMode = WaitMode.ALL

    def __post_init__(self) -> None:
        object.__setattr__(self, "child_pids", tuple(self.child_pids))


@dataclass(frozen=True, slots=True)
class Yield:
    """End an activation, optionally scheduling an explicit continuation."""

    next_event: ContinuationEvent | None = None


@dataclass(frozen=True, slots=True)
class DiscoverImages:
    """Request a factory-free snapshot of the Capability Catalog."""


@dataclass(frozen=True, slots=True)
class InvokeResource:
    """Invoke one explicitly bound Host resource as the current Process."""

    binding_id: ResourceBindingId
    operation: str
    input: Any = None

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("resource operation must not be empty")


@dataclass(frozen=True, slots=True)
class Exit:
    """Attempt to commit successful process completion."""

    result: Any = None


@dataclass(frozen=True, slots=True)
class Fail:
    """Attempt to commit failed process completion."""

    error: ProcessError | str


ProcessAction: TypeAlias = (
    Send
    | Spawn
    | Cancel
    | Detach
    | Wait
    | DiscoverImages
    | InvokeResource
    | Yield
    | Exit
    | Fail
)
