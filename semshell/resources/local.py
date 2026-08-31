"""Read-only local workspace bridge for trusted temporary trees."""

from __future__ import annotations

from pathlib import Path

from semshell.resources.bridge import ResourceBridgeError
from semshell.resources.path import read_text_path
from semshell.resources.types import ResourceErrorCode, ResourceInvocation


class LocalWorkspaceBridge:
    """Expose bounded UTF-8 reads below one startup-fixed local root."""

    def __init__(
        self,
        root: Path,
        *,
        max_path_length: int = 256,
        max_segments: int = 32,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        if min(max_path_length, max_segments, max_output_bytes) <= 0:
            raise ValueError("resource limits must be positive")
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise ValueError("workspace root must be a directory")
        self._root = resolved_root
        self.max_path_length = max_path_length
        self.max_segments = max_segments
        self.max_output_bytes = max_output_bytes
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
        try:
            candidate = self._root.joinpath(*segments).resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise ResourceBridgeError(ResourceErrorCode.NOT_FOUND) from exc
        except OSError as exc:
            raise ResourceBridgeError(ResourceErrorCode.BRIDGE_FAILURE) from exc
        if not candidate.is_relative_to(self._root):
            raise ResourceBridgeError(ResourceErrorCode.MALFORMED_INPUT)
        if not candidate.is_file():
            raise ResourceBridgeError(ResourceErrorCode.NOT_FOUND)
        try:
            with candidate.open("rb") as source:
                data = source.read(self.max_output_bytes + 1)
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
            raise ResourceBridgeError(ResourceErrorCode.NOT_FOUND) from exc
        except OSError as exc:
            raise ResourceBridgeError(ResourceErrorCode.BRIDGE_FAILURE) from exc
        if len(data) > self.max_output_bytes:
            raise ResourceBridgeError(ResourceErrorCode.LIMIT_EXCEEDED)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResourceBridgeError(ResourceErrorCode.BRIDGE_FAILURE) from exc
