"""Static software definitions and single-use spawn requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from semshell.security.authority import Authority
from semshell.security.principal import Principal
from semshell.values import freeze_public_value

if TYPE_CHECKING:
    from semshell.software.program import ProcessProgram


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """A semantic interface advertised by a process image."""

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    side_effects: tuple[str, ...] = ()
    required_authority: Authority = field(default_factory=Authority.empty)
    estimated_cost: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("capability name must not be empty")
        object.__setattr__(
            self, "input_schema", freeze_public_value(self.input_schema)
        )
        object.__setattr__(
            self, "output_schema", freeze_public_value(self.output_schema)
        )
        object.__setattr__(self, "side_effects", tuple(self.side_effects))
        object.__setattr__(
            self, "estimated_cost", freeze_public_value(self.estimated_cost)
        )


@dataclass(frozen=True, slots=True)
class ProcessImage:
    """Immutable, versioned logical executable definition."""

    image_id: str
    version: str
    factory: Callable[[], ProcessProgram]
    capabilities: tuple[CapabilitySpec, ...] = ()
    authority_requirements: Authority = field(default_factory=Authority.empty)
    authority_ceiling: Authority | None = None
    execute_principals: frozenset[Principal] | None = None
    description: str = ""
    trust_metadata: Mapping[str, Any] = field(default_factory=dict)
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.image_id:
            raise ValueError("image ID must not be empty")
        if not self.version:
            raise ValueError("image version must not be empty")
        names = [capability.name for capability in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("an image cannot provide duplicate capabilities")
        if any(not name for name in self.required_capabilities):
            raise ValueError("required capability names must not be empty")
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("an image cannot require duplicate capabilities")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if self.execute_principals is not None:
            object.__setattr__(
                self, "execute_principals", frozenset(self.execute_principals)
            )
        object.__setattr__(
            self, "trust_metadata", freeze_public_value(self.trust_metadata)
        )
        object.__setattr__(
            self, "input_schema", freeze_public_value(self.input_schema)
        )
        object.__setattr__(
            self, "output_schema", freeze_public_value(self.output_schema)
        )
        object.__setattr__(
            self, "required_capabilities", tuple(self.required_capabilities)
        )

    @property
    def reference(self) -> str:
        """Return the exact catalog reference for this image version."""

        return f"{self.image_id}@{self.version}"

    def describe(self) -> ProcessImageDescriptor:
        """Return a transport-neutral view without the executable factory."""

        return ProcessImageDescriptor(
            image_id=self.image_id,
            version=self.version,
            capabilities=self.capabilities,
            authority_requirements=self.authority_requirements,
            authority_ceiling=self.authority_ceiling,
            execute_principals=self.execute_principals,
            description=self.description,
            trust_metadata=self.trust_metadata,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            required_capabilities=self.required_capabilities,
        )


@dataclass(frozen=True, slots=True)
class ProcessImageDescriptor:
    """Immutable transport-neutral metadata for one exact image version."""

    image_id: str
    version: str
    capabilities: tuple[CapabilitySpec, ...] = ()
    authority_requirements: Authority = field(default_factory=Authority.empty)
    authority_ceiling: Authority | None = None
    execute_principals: frozenset[Principal] | None = None
    description: str = ""
    trust_metadata: Mapping[str, Any] = field(default_factory=dict)
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.image_id or not self.version:
            raise ValueError("image descriptor identity must not be empty")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if self.execute_principals is not None:
            object.__setattr__(
                self, "execute_principals", frozenset(self.execute_principals)
            )
        object.__setattr__(
            self, "trust_metadata", freeze_public_value(self.trust_metadata)
        )
        object.__setattr__(
            self, "input_schema", freeze_public_value(self.input_schema)
        )
        object.__setattr__(
            self, "output_schema", freeze_public_value(self.output_schema)
        )
        object.__setattr__(
            self, "required_capabilities", tuple(self.required_capabilities)
        )

    @property
    def reference(self) -> str:
        """Return the exact catalog reference represented by this descriptor."""

        return f"{self.image_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    """A single-use request to create one process."""

    image: str | None = None
    capability: str | None = None
    input: Any = None
    requested_authority: Authority = field(default_factory=Authority.empty)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provider: str | None = None

    def __post_init__(self) -> None:
        if (self.image is None) == (self.capability is None):
            raise ValueError("specify exactly one of image or capability")
        if self.provider is not None and self.capability is None:
            raise ValueError("provider requires capability resolution")
        if self.provider == "":
            raise ValueError("provider must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
