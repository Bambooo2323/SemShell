"""Immutable values for generic Host resource invocation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from semshell.security.authority import Authority, Permission
from semshell.security.principal import Principal


@dataclass(frozen=True, slots=True, order=True)
class ResourceBindingId:
    """Opaque binding identity unique within one Kernel lifetime."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("resource binding ID must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class ResourceInvocationId:
    """Kernel-allocated monotonic identity for one evaluated invocation."""

    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("resource invocation ID must be positive")

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class ResourceBindingDescriptor:
    """Host-visible immutable metadata without a bridge or Host location."""

    binding_id: ResourceBindingId
    resource_kind: str
    operations: Mapping[str, Permission]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_kind:
            raise ValueError("resource kind must not be empty")
        operations = dict(self.operations)
        if not operations or any(not name for name in operations):
            raise ValueError("resource operations must have non-empty names")
        if any(
            permission.scope != self.binding_id.value
            for permission in operations.values()
        ):
            raise ValueError("operation Permission scope must equal the binding ID")
        object.__setattr__(self, "operations", MappingProxyType(operations))
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )


class ResourceErrorCode(StrEnum):
    """Closed stable error codes for the minimal resource protocol."""

    UNKNOWN_BINDING = "resource.unknown_binding"
    UNSUPPORTED_OPERATION = "resource.unsupported_operation"
    AUTHORITY_DENIED = "resource.authority_denied"
    CAPACITY_EXCEEDED = "resource.capacity_exceeded"
    MALFORMED_INPUT = "resource.malformed_input"
    NOT_FOUND = "resource.not_found"
    LIMIT_EXCEEDED = "resource.limit_exceeded"
    BRIDGE_FAILURE = "resource.bridge_failure"
    CANCELLED = "resource.cancelled"


class ResourceAuditPhase(StrEnum):
    """Append-only phases emitted during resource invocation."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LATE_COMPLETED = "late_completed"
    LATE_FAILED = "late_failed"


@dataclass(frozen=True, slots=True)
class ResourceInvocation:
    """Authenticated immutable invocation constructed by the Kernel."""

    invocation_id: ResourceInvocationId
    binding_id: ResourceBindingId
    operation: str
    caller_pid: int
    principal: Principal
    authority: Authority
    input: Any

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("resource operation must not be empty")
        if self.caller_pid <= 0:
            raise ValueError("resource caller PID must be positive")
        object.__setattr__(self, "input", freeze_resource_value(self.input))


@dataclass(frozen=True, slots=True)
class ResourceAuditEvent:
    """Payload-free immutable audit event for one invocation phase."""

    occurred_at: datetime
    invocation_id: ResourceInvocationId
    caller_pid: int
    principal: Principal
    binding_id: ResourceBindingId
    operation: str
    phase: ResourceAuditPhase
    required_permission: Permission | None = None
    error_code: ResourceErrorCode | None = None

    def __post_init__(self) -> None:
        if self.caller_pid <= 0 or not self.operation:
            raise ValueError("resource audit caller and operation must be valid")


def freeze_resource_value(value: Any, _active: set[int] | None = None) -> Any:
    """Recursively copy a supported JSON-like value into immutable containers."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("resource input numbers must be finite")
        return value
    if not isinstance(value, (list, tuple, Mapping)):
        raise TypeError("resource input must contain only JSON-like values")

    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        raise ValueError("resource input must not contain cycles")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("resource input mapping keys must be strings")
            return MappingProxyType(
                {
                    key: freeze_resource_value(item, active)
                    for key, item in value.items()
                }
            )
        return tuple(freeze_resource_value(item, active) for item in value)
    finally:
        active.remove(identity)
