"""Generic Host resource bindings available to the SemShell runtime."""

from semshell.resources.bridge import HostResourceBridge, ResourceBridgeError
from semshell.resources.memory import InMemoryResourceBridge
from semshell.resources.registry import ResourceBinding, ResourceRegistry
from semshell.resources.types import (
    ResourceAuditEvent,
    ResourceAuditPhase,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceErrorCode,
    ResourceInvocation,
    ResourceInvocationId,
    freeze_resource_value,
)

__all__ = [
    "HostResourceBridge",
    "InMemoryResourceBridge",
    "ResourceAuditEvent",
    "ResourceAuditPhase",
    "ResourceBinding",
    "ResourceBindingDescriptor",
    "ResourceBindingId",
    "ResourceBridgeError",
    "ResourceErrorCode",
    "ResourceInvocation",
    "ResourceInvocationId",
    "ResourceRegistry",
    "freeze_resource_value",
]
