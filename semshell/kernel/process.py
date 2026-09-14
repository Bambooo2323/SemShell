"""Process lifecycle and result value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from semshell.resources.types import ResourceInvocationId
from semshell.security.authority import Authority
from semshell.security.principal import Principal
from semshell.values import freeze_public_value


class ProcessState(StrEnum):
    """Normative process states from the SemShell 0.1 semantics."""

    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    CANCELLING = "CANCELLING"
    FAILING = "FAILING"
    EXITED = "EXITED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


COMPLETION_STATES = frozenset(
    {ProcessState.EXITED, ProcessState.FAILED, ProcessState.CANCELLED}
)
TERMINAL_STATES = COMPLETION_STATES


class ErrorOrigin(StrEnum):
    """Stable origin categories for public process errors."""

    PROGRAM = "program"
    KERNEL = "kernel"
    POLICY = "policy"
    HOST = "host"


@dataclass(frozen=True, slots=True)
class ProcessError:
    """Structured public error carried by a failed process or operation."""

    code: str
    message: str
    origin: ErrorOrigin
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    causal_pid: int | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("error code must not be empty")
        if not self.message:
            raise ValueError("error message must not be empty")
        object.__setattr__(self, "details", freeze_public_value(self.details))


@dataclass(frozen=True, slots=True)
class ProcessContext:
    """Kernel-owned context supplied to every program activation."""

    pid: int
    owner_pid: int | None
    spawned_by_pid: int | None
    image_id: str
    image_version: str
    principal: Principal
    authority: Authority
    input: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_public_value(self.metadata))


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Immutable result published exactly once by a completed process."""

    pid: int
    image_id: str
    image_version: str
    state: ProcessState
    started_at: datetime
    completed_at: datetime
    result: Any = None
    error: ProcessError | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in COMPLETION_STATES:
            raise ValueError("a process result requires a completion state")
        if self.state is ProcessState.FAILED and self.error is None:
            raise ValueError("a failed process result requires an error")
        object.__setattr__(self, "result", freeze_public_value(self.result))
        object.__setattr__(self, "usage", freeze_public_value(self.usage))
        object.__setattr__(self, "diagnostics", freeze_public_value(self.diagnostics))


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """Read-only process state returned by inspection APIs."""

    pid: int
    owner_pid: int | None
    spawned_by_pid: int | None
    image_id: str
    image_version: str
    principal: Principal
    authority: Authority
    state: ProcessState
    child_pids: tuple[int, ...] = ()
    waiting_for: tuple[int, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    result: ProcessResult | None = None
    pending_resource_invocation_id: ResourceInvocationId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "child_pids", tuple(self.child_pids))
        object.__setattr__(self, "waiting_for", tuple(self.waiting_for))
        object.__setattr__(self, "metadata", freeze_public_value(self.metadata))
