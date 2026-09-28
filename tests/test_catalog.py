"""Capability Catalog, upgrade, unload, and control-boundary tests."""

from __future__ import annotations

from typing import Any

import pytest

from semshell import CapabilitySpec, ProcessImage, ProcessImageDescriptor, ProcessSpec
from semshell.kernel import Exit, ProcessContext, ProcessKernel, Started
from semshell.security import Principal
from semshell.software.catalog import ProcessCatalog


class VersionProgram:
    def __init__(self, version: str) -> None:
        self.version = version

    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Exit(self.version)
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


def image(image_id: str, version: str, capability: str = "demo") -> ProcessImage:
    return ProcessImage(
        image_id=image_id,
        version=version,
        factory=lambda: VersionProgram(version),
        capabilities=(
            CapabilitySpec(
                name=capability,
                description="Demonstrate catalog resolution",
                input_schema={"type": "string"},
                output_schema={"type": "string"},
                side_effects=("none",),
                estimated_cost={"units": 1},
            ),
        ),
        input_schema={"type": "string"},
        output_schema={"type": "string"},
        required_capabilities=("audit.write",),
        trust_metadata={"source": "test"},
    )


def test_multiple_providers_require_an_exact_caller_selection() -> None:
    catalog = ProcessCatalog()
    first = image("first", "1")
    second = image("second", "1")
    other = image("other", "1", capability="other")
    catalog.register(first)
    catalog.register(second)
    catalog.register(other)

    assert catalog.providers_for("demo") == (first, second)
    with pytest.raises(LookupError, match="ambiguous capability"):
        catalog.resolve_capability("demo")
    assert catalog.resolve_capability("demo", provider="second@1") is second
    with pytest.raises(LookupError, match="does not provide"):
        catalog.resolve_capability("demo", provider="other@1")


def test_image_descriptor_contains_metadata_but_not_factory() -> None:
    descriptor = image("demo-image", "1").describe()

    assert isinstance(descriptor, ProcessImageDescriptor)
    assert descriptor.reference == "demo-image@1"
    assert descriptor.required_capabilities == ("audit.write",)
    assert descriptor.input_schema == {"type": "string"}
    assert descriptor.capabilities[0].estimated_cost == {"units": 1}
    assert not hasattr(descriptor, "factory")


@pytest.mark.parametrize(
    ("kind", "field_name"),
    [
        (kind, field_name)
        for kind, fields in (
            ("capability", ("input_schema", "output_schema", "estimated_cost")),
            ("image", ("input_schema", "output_schema", "trust_metadata")),
            ("descriptor", ("input_schema", "output_schema", "trust_metadata")),
        )
        for field_name in fields
    ],
)
def test_catalog_metadata_is_recursively_immutable(kind: str, field_name: str) -> None:
    source = {"properties": {"name": {"enum": ["original"]}}}
    kwargs: dict[str, Any] = {field_name: source}
    value: Any
    if kind == "capability":
        value = CapabilitySpec(name="demo", description="Demo", **kwargs)
    elif kind == "image":
        value = ProcessImage(
            image_id="demo",
            version="1",
            factory=lambda: VersionProgram("1"),
            **kwargs,
        )
    else:
        value = ProcessImageDescriptor(image_id="demo", version="1", **kwargs)

    source["properties"]["name"]["enum"].append("changed")
    metadata = getattr(value, field_name)
    assert metadata["properties"]["name"]["enum"] == ("original",)
    with pytest.raises(TypeError):
        metadata["properties"]["name"]["enum"] = ("changed",)
    if kind == "image":
        exposed = getattr(value.describe(), field_name)
        with pytest.raises(TypeError):
            exposed["properties"]["name"]["enum"] = ("changed",)
        assert metadata["properties"]["name"]["enum"] == ("original",)


@pytest.mark.asyncio
async def test_live_registration_keeps_completed_versions_observable() -> None:
    catalog = ProcessCatalog()
    catalog.register(image("worker", "1"))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    principal = Principal.parse("human:test")
    first_pid = await kernel.spawn(ProcessSpec(image="worker@1"), principal=principal)
    kernel.register_image(image("worker", "2"))
    with pytest.raises(LookupError, match="ambiguous capability"):
        await kernel.spawn(ProcessSpec(capability="demo"), principal=principal)
    second_pid = await kernel.spawn(
        ProcessSpec(capability="demo", provider="worker@2"), principal=principal
    )

    first_result = await kernel.wait(first_pid, timeout=1)
    second_result = await kernel.wait(second_pid, timeout=1)

    assert first_result.result == "1"
    assert second_result.result == "2"
    assert kernel.inspect(first_pid).image_version == "1"
    assert kernel.inspect(first_pid).result is first_result
    assert tuple(item.reference for item in kernel.list_images()) == (
        "worker@1",
        "worker@2",
    )
    assert kernel.resolve_image(image="worker@2").version == "2"
    await kernel.stop()


@pytest.mark.asyncio
async def test_kernel_catalog_results_are_factory_free() -> None:
    catalog = ProcessCatalog()
    catalog.register(image("first", "1"))
    catalog.register(image("second", "1"))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    listed = kernel.list_images()
    resolved = kernel.resolve_image(capability="demo", provider="second@1")
    assert all(isinstance(item, ProcessImageDescriptor) for item in listed)
    assert resolved.reference == "second@1"
    assert tuple(item.reference for item in kernel.list_images()) == (
        "first@1",
        "second@1",
    )
    await kernel.stop()
