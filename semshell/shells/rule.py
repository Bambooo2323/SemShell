"""Deterministic rule Operator implemented as an ordinary ProcessProgram."""

from __future__ import annotations

from collections.abc import Callable

from semshell.kernel import (
    ChildrenCompleted,
    DiscoverImages,
    ImagesDiscovered,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    Started,
)
from semshell.shells.base import OperatorTask, complete_task, spawn_task
from semshell.software.image import ProcessImageDescriptor

Rule = Callable[[OperatorTask, tuple[ProcessImageDescriptor, ...]], ProcessAction]


class RuleShell:
    """Apply a deterministic strategy to the same task and Catalog view."""

    def __init__(self, rule: Rule = spawn_task) -> None:
        self._rule = rule
        self._task: OperatorTask | None = None

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if not isinstance(context.input, OperatorTask):
                raise TypeError("RuleShell input must be an OperatorTask")
            self._task = context.input
            return DiscoverImages()
        if isinstance(event, ImagesDiscovered):
            if self._task is None:
                raise RuntimeError("RuleShell has no active task")
            return self._rule(self._task, event.images)
        if isinstance(event, ChildrenCompleted):
            return complete_task(event)
        raise RuntimeError(f"unsupported RuleShell event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None
