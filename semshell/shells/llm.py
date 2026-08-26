"""Semantic-backend Operator implemented as an ordinary ProcessProgram."""

from __future__ import annotations

import json

from semshell.kernel import (
    ChildrenCompleted,
    DiscoverImages,
    ImagesDiscovered,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    Started,
)
from semshell.llm import LLMRequest, SemanticBackend
from semshell.shells.base import OperatorTask, complete_task
from semshell.shells.codec import action_from_data


class LLMShell:
    """Use a model-neutral backend to choose an ordinary Process Action."""

    def __init__(self, backend: SemanticBackend, *, model: str) -> None:
        self._backend = backend
        self._model = model
        self._task: OperatorTask | None = None

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if not isinstance(context.input, OperatorTask):
                raise TypeError("LLMShell input must be an OperatorTask")
            self._task = context.input
            return DiscoverImages()
        if isinstance(event, ImagesDiscovered):
            if self._task is None:
                raise RuntimeError("LLMShell has no active task")
            response = await self._backend.generate(
                LLMRequest(
                    model=self._model,
                    input={
                        "task": {
                            "capability": self._task.capability,
                            "input": self._task.input,
                        },
                        "images": [
                            {
                                "reference": image.reference,
                                "capabilities": [
                                    capability.name
                                    for capability in image.capabilities
                                ],
                            }
                            for image in event.images
                        ],
                    },
                    instructions=(
                        "Return one JSON Process Action. Use discovered capabilities "
                        "and do not call external tools."
                    ),
                )
            )
            return action_from_data(json.loads(response.output_text))
        if isinstance(event, ChildrenCompleted):
            return complete_task(event)
        raise RuntimeError(f"unsupported LLMShell event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None
