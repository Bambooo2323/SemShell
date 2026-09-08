"""Mutable process-control records owned exclusively by the kernel."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from semshell.kernel.events import ProcessEvent
from semshell.kernel.process import (
    ProcessContext,
    ProcessError,
    ProcessResult,
    ProcessState,
    WaitMode,
)
from semshell.resources.types import ResourceInvocation, ResourceInvocationId
from semshell.security.authority import Permission
from semshell.software.program import ProcessProgram


@dataclass(slots=True)
class ResourceTaskRecord:
    """Kernel-owned lifetime record for one live Host bridge task."""

    invocation: ResourceInvocation
    required_permission: Permission
    task: asyncio.Task[None] | None = None
    suppressed: bool = False
    slot_released: bool = False


@dataclass(frozen=True, slots=True)
class TerminalDecision:
    """Frozen winner of a Process's terminal competition."""

    state: ProcessState
    decided_at: datetime
    result: Any = None
    error: ProcessError | None = None


@dataclass(slots=True)
class ProcessControlBlock:
    """Mutable scheduling state that is never exposed to user-space code."""

    context: ProcessContext
    program: ProcessProgram
    state: ProcessState
    started_at: datetime
    completion: asyncio.Future[ProcessResult]
    mailbox: deque[ProcessEvent] = field(default_factory=deque)
    child_pids: set[int] = field(default_factory=set)
    waiting_for: frozenset[int] | None = None
    wait_mode: WaitMode | None = None
    result: ProcessResult | None = None
    runner: asyncio.Task[None] | None = None
    decision: TerminalDecision | None = None
    finalizer_task: asyncio.Task[None] | None = None
    stop_task: asyncio.Task[None] | None = None
    operation_completion: asyncio.Future[ProcessResult] | None = None
    operation_callback: Callable[[asyncio.Future[ProcessResult]], None] | None = None
    pending_error: ProcessError | None = None
    pending_resource_invocation_id: ResourceInvocationId | None = None
    private: dict[str, Any] = field(default_factory=dict)

    @property
    def pid(self) -> int:
        return self.context.pid
