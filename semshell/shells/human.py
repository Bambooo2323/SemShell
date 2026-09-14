"""Human-selected Operator implemented as an ordinary ProcessProgram."""

from __future__ import annotations

from semshell.kernel import (
    ChildrenCompleted,
    ConsoleInput,
    DiscoverImages,
    ImagesDiscovered,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    Spawned,
    Started,
    Yield,
)
from semshell.shells.base import (
    OperatorTask,
    complete_task,
    spawn_task,
    wait_for_spawn,
)


class HumanShell:
    """Translate a structured task or bound-console input into Process Actions."""

    def __init__(self) -> None:
        self._task: OperatorTask | None = None

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if context.input is None:
                return Yield()
            if not isinstance(context.input, OperatorTask):
                raise TypeError("HumanShell input must be an OperatorTask")
            self._task = context.input
            return DiscoverImages()
        if isinstance(event, ConsoleInput):
            if not isinstance(event.payload, OperatorTask):
                raise TypeError("console input must be an OperatorTask")
            self._task = event.payload
            return DiscoverImages()
        if isinstance(event, ImagesDiscovered):
            if self._task is None:
                raise RuntimeError("HumanShell has no active task")
            return spawn_task(self._task, event.images)
        if isinstance(event, Spawned):
            return wait_for_spawn(event)
        if isinstance(event, ChildrenCompleted):
            return complete_task(event)
        raise RuntimeError(f"unsupported HumanShell event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None
