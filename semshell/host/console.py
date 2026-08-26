"""Minimal Host console binding for one admitted Process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semshell.kernel.kernel import ProcessKernel
from semshell.security.principal import Principal


@dataclass(frozen=True, slots=True)
class ConsoleBridge:
    """Deliver Host input only to the Process selected when the bridge is made."""

    kernel: ProcessKernel
    target_pid: int
    principal: Principal

    def __post_init__(self) -> None:
        if self.target_pid <= 0:
            raise ValueError("console target PID must be positive")
        self.kernel.inspect(self.target_pid)

    async def write_input(self, payload: Any) -> None:
        """Deliver one principal-attributed console event to the bound Process."""

        await self.kernel.deliver_console_input(
            self.target_pid, payload, principal=self.principal
        )
