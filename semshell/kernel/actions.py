"""Immutable actions returned by process programs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from semshell.kernel.events import ContinuationEvent
from semshell.kernel.operations import (
    CancelProcess,
    DetachProcess,
    SendMessage,
    SpawnProcesses,
)
from semshell.kernel.process import ProcessError, WaitMode
from semshell.resources.types import ResourceBindingId

Send = SendMessage
Cancel = CancelProcess
Detach = DetachProcess


@dataclass(frozen=True, slots=True)
class Spawn(SpawnProcesses):
    """Request atomic admission of one or more process specifications."""

    wait: bool = False
    wait_mode: WaitMode = WaitMode.ALL

    def __post_init__(self) -> None:
        super(Spawn, self).__post_init__()


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
