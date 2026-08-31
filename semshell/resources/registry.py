"""Startup-only immutable Host resource registry."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from semshell.resources.bridge import HostResourceBridge
from semshell.resources.types import ResourceBindingDescriptor, ResourceBindingId


@dataclass(frozen=True, slots=True)
class ResourceBinding:
    """Trusted pairing of public metadata and a passive Host bridge."""

    descriptor: ResourceBindingDescriptor
    bridge: HostResourceBridge


class ResourceRegistry:
    """Immutable exact binding lookup constructed before Kernel start."""

    def __init__(self, bindings: Iterable[ResourceBinding] = ()) -> None:
        indexed: dict[ResourceBindingId, ResourceBinding] = {}
        for binding in bindings:
            binding_id = binding.descriptor.binding_id
            if binding_id in indexed:
                raise ValueError(f"duplicate resource binding: {binding_id}")
            indexed[binding_id] = binding
        self._bindings = MappingProxyType(indexed)

    def get(self, binding_id: ResourceBindingId) -> ResourceBinding | None:
        """Return one exact trusted binding, if present."""

        return self._bindings.get(binding_id)

    def descriptors(self) -> tuple[ResourceBindingDescriptor, ...]:
        """Return Host diagnostic descriptors in deterministic ID order."""

        return tuple(
            self._bindings[binding_id].descriptor
            for binding_id in sorted(self._bindings)
        )
