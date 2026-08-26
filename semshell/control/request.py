"""External envelopes around Kernel-owned control operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from semshell.kernel.operations import (
    EXTERNAL_CONTROL_OPERATION_TYPES,
    ExternalControlOperation,
)

PROTOCOL_VERSION = "0.1"


@dataclass(frozen=True, slots=True, order=True)
class RequestId:
    """Opaque request identity unique within one control session."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("request ID must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """External request envelope with no trusted caller identity fields."""

    request_id: RequestId
    operation: ExternalControlOperation
    protocol_version: str = PROTOCOL_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.protocol_version:
            raise ValueError("protocol version must not be empty")
        if not isinstance(self.operation, EXTERNAL_CONTROL_OPERATION_TYPES):
            raise TypeError("operation is not available to an external session")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
