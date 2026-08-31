"""Passive Host resource bridge protocol and stable expected failures."""

from __future__ import annotations

from typing import Protocol

from semshell.resources.types import ResourceErrorCode, ResourceInvocation

PUBLIC_ERROR_MESSAGES = {
    ResourceErrorCode.MALFORMED_INPUT: "resource input is malformed",
    ResourceErrorCode.NOT_FOUND: "resource was not found",
    ResourceErrorCode.LIMIT_EXCEEDED: "resource limit exceeded",
    ResourceErrorCode.BRIDGE_FAILURE: "resource bridge failed",
}


class ResourceBridgeError(RuntimeError):
    """Expected bridge failure with a closed code and fixed public message."""

    def __init__(self, code: ResourceErrorCode) -> None:
        try:
            message = PUBLIC_ERROR_MESSAGES[code]
        except KeyError as exc:
            raise ValueError("error code is not bridge-originated") from exc
        self.code = code
        super().__init__(message)


class HostResourceBridge(Protocol):
    """Passive Host operation invoked only by the Kernel resource boundary."""

    async def invoke(self, invocation: ResourceInvocation) -> object:
        """Return one value or raise one expected ResourceBridgeError."""
        ...
