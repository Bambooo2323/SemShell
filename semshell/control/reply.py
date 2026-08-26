"""One-shot replies produced by admitted control requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from semshell.control.error import ControlError
from semshell.control.request import PROTOCOL_VERSION, RequestId


class ReplyStatus(StrEnum):
    """Terminal outcomes of an admitted control request."""

    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class ControlReply:
    """The unique terminal reply for one admitted request."""

    request_id: RequestId
    operation: str
    status: ReplyStatus
    value: Any = None
    error: ControlError | None = None
    protocol_version: str = PROTOCOL_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("operation name must not be empty")
        if not self.protocol_version:
            raise ValueError("protocol version must not be empty")
        if self.status is ReplyStatus.SUCCEEDED and self.error is not None:
            raise ValueError("a successful reply cannot contain an error")
        if self.status is not ReplyStatus.SUCCEEDED and self.error is None:
            raise ValueError("a rejected or interrupted reply requires an error")
        if self.error is not None and self.value is not None:
            raise ValueError("a reply cannot contain both a value and an error")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
