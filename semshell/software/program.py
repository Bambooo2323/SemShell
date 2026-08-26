"""User-space process program contract."""

from __future__ import annotations

from typing import Protocol

from semshell.kernel.actions import ProcessAction
from semshell.kernel.events import ProcessEvent
from semshell.kernel.process import ProcessContext


class ProcessProgram(Protocol):
    """Behavior contract implemented by every executable program image."""

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        """Handle exactly one event and return exactly one action."""
        ...

    async def stop(self, reason: str) -> None:
        """Perform bounded best-effort cancellation cleanup."""
        ...
