"""Capability Catalog, upgrade, unload, and control-boundary tests."""

from __future__ import annotations

from typing import Any

import pytest

from semshell import CapabilitySpec, ProcessImage, ProcessImageDescriptor, ProcessSpec
from semshell.control import ControlGateway, ControlRequest, ReplyStatus, RequestId
from semshell.kernel import Exit, ProcessContext, ProcessKernel, Started
from semshell.kernel.errors import OperationDenied
from semshell.kernel.operations import ListImages, ResolveImage, UnregisterImage
from semshell.security import Authority, Principal
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


def control_request(request_id: str, operation: object) -> ControlRequest:
    return ControlRequest(RequestId(request_id), operation)  # type: ignore[arg-type]


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


def test_unregister_removes_provider_indexes_deterministically() -> None:
    catalog = ProcessCatalog()
    first = image("first", "1")
    second = image("second", "1")
    catalog.register(second)
    catalog.register(first)

    removed = catalog.unregister("first@1")

    assert removed is first
    assert catalog.list_images() == (second,)
    assert catalog.providers_for("demo") == (second,)
    assert catalog.resolve_capability("demo") is second


def test_image_descriptor_contains_metadata_but_not_factory() -> None:
    descriptor = image("demo-image", "1").describe()

    assert isinstance(descriptor, ProcessImageDescriptor)
    assert descriptor.reference == "demo-image@1"
    assert descriptor.required_capabilities == ("audit.write",)
    assert descriptor.input_schema == {"type": "string"}
    assert descriptor.capabilities[0].estimated_cost == {"units": 1}
    assert not hasattr(descriptor, "factory")


@pytest.mark.asyncio
async def test_upgrade_keeps_running_version_and_unload_requires_reap() -> None:
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
    with pytest.raises(OperationDenied, match="still in use"):
        kernel.unregister_image("worker@1")
    await kernel.reap(first_pid)
    removed = kernel.unregister_image("worker@1")
    assert removed.reference == "worker@1"
    assert kernel.resolve_image(image="worker@2").version == "2"
    await kernel.stop()


@pytest.mark.asyncio
async def test_control_catalog_results_are_factory_free_and_unload_is_safe() -> None:
    catalog = ProcessCatalog()
    catalog.register(image("first", "1"))
    catalog.register(image("second", "1"))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )

    listed = await gateway.submit(session, control_request("list", ListImages()))
    list_reply = await listed.wait_reply()
    resolved = await gateway.submit(
        session,
        control_request(
            "resolve", ResolveImage(capability="demo", provider="second@1")
        ),
    )
    resolve_reply = await resolved.wait_reply()
    removed = await gateway.submit(
        session, control_request("remove", UnregisterImage("first@1"))
    )

    remove_reply = await removed.wait_reply()
    assert list_reply.status is ReplyStatus.SUCCEEDED
    assert all(isinstance(item, ProcessImageDescriptor) for item in list_reply.value)
    assert resolve_reply.value.reference == "second@1"
    assert remove_reply.value.reference == "first@1"
    assert kernel.list_images() == (resolve_reply.value,)
    await gateway.close_session(session)
    await kernel.stop()
