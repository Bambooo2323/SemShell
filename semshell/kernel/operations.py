"""Kernel-owned operation payloads shared by trusted invocation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from semshell.kernel.events import MessageKind
from semshell.kernel.process import CancelMode
from semshell.software.image import ProcessImage, ProcessSpec


@dataclass(frozen=True, slots=True)
class ListImages:
    """Create a deterministic snapshot of registered process images."""


@dataclass(frozen=True, slots=True)
class ListProcesses:
    """Create a deterministic snapshot of the live Process Table."""


@dataclass(frozen=True, slots=True)
class ResolveImage:
    """Resolve exactly one image reference or semantic capability."""

    image: str | None = None
    capability: str | None = None
    provider: str | None = None

    def __post_init__(self) -> None:
        if (self.image is None) == (self.capability is None):
            raise ValueError("specify exactly one of image or capability")
        if self.provider is not None and self.capability is None:
            raise ValueError("provider requires capability resolution")
        if self.provider == "":
            raise ValueError("provider must not be empty")


@dataclass(frozen=True, slots=True)
class RegisterImage:
    """Load a host-constructed image through a trusted in-process boundary."""

    image: ProcessImage


@dataclass(frozen=True, slots=True)
class UnregisterImage:
    """Unload one exact image version when it is not in use."""

    reference: str

    def __post_init__(self) -> None:
        if not self.reference:
            raise ValueError("image reference must not be empty")


@dataclass(frozen=True, slots=True)
class SpawnProcesses:
    """Admit ProcessSpecs under invocation-bound caller identity."""

    specs: tuple[ProcessSpec, ...]

    def __post_init__(self) -> None:
        if not self.specs:
            raise ValueError(
                "SpawnProcesses requires at least one process specification"
            )
        object.__setattr__(self, "specs", tuple(self.specs))


@dataclass(frozen=True, slots=True)
class SendMessage:
    """Enqueue a message with its source inferred from invocation context."""

    target_pid: int
    payload: Any
    kind: MessageKind = MessageKind.EVENT
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.target_pid <= 0:
            raise ValueError("target PID must be positive")


@dataclass(frozen=True, slots=True)
class WaitProcess:
    """Externally observe a Process until it publishes a terminal result."""

    pid: int
    timeout: float | None = None

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("PID must be positive")
        if self.timeout is not None and self.timeout < 0:
            raise ValueError("timeout must not be negative")


@dataclass(frozen=True, slots=True)
class CancelProcess:
    """Request cancellation of a Process or attached Process subtree."""

    target_pid: int
    mode: CancelMode = CancelMode.SELF
    reason: str = "cancelled"

    def __post_init__(self) -> None:
        if self.target_pid <= 0:
            raise ValueError("target PID must be positive")
        if not self.reason:
            raise ValueError("cancellation reason must not be empty")


@dataclass(frozen=True, slots=True)
class DetachProcess:
    """Remove lifecycle ownership from one direct attached child."""

    child_pid: int

    def __post_init__(self) -> None:
        if self.child_pid <= 0:
            raise ValueError("child PID must be positive")


@dataclass(frozen=True, slots=True)
class InspectProcess:
    """Create one immutable Process snapshot."""

    pid: int

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("PID must be positive")


@dataclass(frozen=True, slots=True)
class InspectTree:
    """Create an immutable Process subtree snapshot."""

    pid: int

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("PID must be positive")


@dataclass(frozen=True, slots=True)
class ReapProcess:
    """Remove one completed Process from the live Process Table."""

    pid: int

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("PID must be positive")


KernelOperation: TypeAlias = (
    ListImages
    | ListProcesses
    | ResolveImage
    | RegisterImage
    | UnregisterImage
    | SpawnProcesses
    | SendMessage
    | WaitProcess
    | CancelProcess
    | DetachProcess
    | InspectProcess
    | InspectTree
    | ReapProcess
)

# External sessions have no PID and therefore cannot originate Process IPC or
# detach another Process's child. Console input uses a separately bound Host
# bridge and is not a generic Control operation.
ExternalControlOperation: TypeAlias = (
    ListImages
    | ListProcesses
    | ResolveImage
    | UnregisterImage
    | SpawnProcesses
    | WaitProcess
    | CancelProcess
    | InspectProcess
    | InspectTree
    | ReapProcess
)

EXTERNAL_CONTROL_OPERATION_TYPES = (
    ListImages,
    ListProcesses,
    ResolveImage,
    UnregisterImage,
    SpawnProcesses,
    WaitProcess,
    CancelProcess,
    InspectProcess,
    InspectTree,
    ReapProcess,
)
