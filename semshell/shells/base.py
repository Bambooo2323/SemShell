"""Shared task and transition helpers for Operator Processes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semshell.kernel import ChildrenCompleted, Exit, Spawn
from semshell.kernel.actions import ProcessAction
from semshell.software.image import ProcessImageDescriptor, ProcessSpec


@dataclass(frozen=True, slots=True)
class OperatorTask:
    """One minimal capability request shared by every Operator implementation."""

    capability: str
    input: Any = None

    def __post_init__(self) -> None:
        if not self.capability:
            raise ValueError("operator task capability must not be empty")


def spawn_task(
    task: OperatorTask, images: tuple[ProcessImageDescriptor, ...]
) -> Spawn:
    """Validate discovery and create the ordinary Action for one task."""

    providers = [
        image
        for image in images
        if any(item.name == task.capability for item in image.capabilities)
    ]
    if len(providers) != 1:
        raise LookupError(
            f"task capability requires exactly one provider: {task.capability}"
        )
    return Spawn(
        (ProcessSpec(capability=task.capability, input=task.input),), wait=True
    )


def complete_task(event: ChildrenCompleted) -> ProcessAction:
    """Complete an Operator after its one attached task Process finishes."""

    if len(event.results) != 1:
        raise RuntimeError("operator task requires exactly one child result")
    result = event.results[0]
    if result.error is not None:
        return Exit({"error": result.error.code, "message": result.error.message})
    return Exit(result.result)
