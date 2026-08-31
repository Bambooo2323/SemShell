"""Deterministic in-memory implementation of the minimal read_text bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from semshell.resources.bridge import ResourceBridgeError
from semshell.resources.path import read_text_path
from semshell.resources.types import ResourceErrorCode, ResourceInvocation


class InMemoryResourceBridge:
    """Read text from a frozen guest-path mapping without external I/O."""

    def __init__(
        self,
        files: Mapping[str, str],
        *,
        max_path_length: int = 256,
        max_segments: int = 32,
        max_output_bytes: int = 1_000_000,
        release: asyncio.Event | None = None,
    ) -> None:
        if min(max_path_length, max_segments, max_output_bytes) <= 0:
            raise ValueError("resource limits must be positive")
        self._files = dict(files)
        self.max_path_length = max_path_length
        self.max_segments = max_segments
        self.max_output_bytes = max_output_bytes
        self.release = release
        self.invocations: list[ResourceInvocation] = []

    async def invoke(self, invocation: ResourceInvocation) -> object:
        self.invocations.append(invocation)
        if invocation.operation != "read_text":
            raise ResourceBridgeError(ResourceErrorCode.MALFORMED_INPUT)
        segments = read_text_path(
            invocation.input,
            max_path_length=self.max_path_length,
            max_segments=self.max_segments,
        )
        if self.release is not None:
            await self.release.wait()
        path = "/".join(segments)
        try:
            value = self._files[path]
        except KeyError as exc:
            raise ResourceBridgeError(ResourceErrorCode.NOT_FOUND) from exc
        if len(value.encode("utf-8")) > self.max_output_bytes:
            raise ResourceBridgeError(ResourceErrorCode.LIMIT_EXCEEDED)
        return value
