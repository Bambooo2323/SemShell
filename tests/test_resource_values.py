"""Public value and fake-bridge tests for the minimal resource boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from semshell.resources import (
    InMemoryResourceBridge,
    ResourceAuditEvent,
    ResourceAuditPhase,
    ResourceBinding,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceBridgeError,
    ResourceErrorCode,
    ResourceInvocation,
    ResourceInvocationId,
    ResourceRegistry,
    freeze_resource_value,
)
from semshell.security import Authority, Permission, Principal

BINDING_ID = ResourceBindingId("binding-1")
READ_PERMISSION = Permission("workspace.read", str(BINDING_ID))


def descriptor() -> ResourceBindingDescriptor:
    return ResourceBindingDescriptor(
        BINDING_ID,
        "workspace",
        {"read_text": READ_PERMISSION},
        {"label": "demo"},
    )


def invocation(input_value: object, *, operation: str = "read_text") -> ResourceInvocation:
    return ResourceInvocation(
        ResourceInvocationId(1),
        BINDING_ID,
        operation,
        7,
        Principal.parse("human:test"),
        Authority.of((READ_PERMISSION,)),
        input_value,
    )


def test_binding_descriptor_freezes_trusted_metadata() -> None:
    operations = {"read_text": READ_PERMISSION}
    metadata = {"label": "demo"}
    value = ResourceBindingDescriptor(BINDING_ID, "workspace", operations, metadata)
    operations.clear()
    metadata.clear()

    assert value.operations == {"read_text": READ_PERMISSION}
    assert value.metadata == {"label": "demo"}
    with pytest.raises(TypeError):
        value.operations["write"] = READ_PERMISSION  # type: ignore[index]


def test_descriptor_requires_binding_scoped_permissions() -> None:
    with pytest.raises(ValueError, match="scope"):
        ResourceBindingDescriptor(
            BINDING_ID,
            "workspace",
            {"read_text": Permission("workspace.read", "display-name")},
        )


def test_registry_is_exact_immutable_and_deterministic() -> None:
    first = ResourceBinding(descriptor(), InMemoryResourceBridge({"a.txt": "a"}))
    second_id = ResourceBindingId("binding-2")
    second = ResourceBinding(
        ResourceBindingDescriptor(
            second_id,
            "workspace",
            {"read_text": Permission("workspace.read", str(second_id))},
        ),
        InMemoryResourceBridge({"b.txt": "b"}),
    )
    registry = ResourceRegistry((second, first))

    assert registry.get(BINDING_ID) is first
    assert registry.get(ResourceBindingId("missing")) is None
    assert [item.binding_id for item in registry.descriptors()] == [
        BINDING_ID,
        second_id,
    ]
    with pytest.raises(ValueError, match="duplicate"):
        ResourceRegistry((first, first))


def test_resource_input_is_a_deep_immutable_snapshot() -> None:
    source = {"path": "docs/readme.txt", "nested": [1, {"ok": True}]}
    frozen = freeze_resource_value(source)
    source["path"] = "changed"
    source["nested"] = []

    assert frozen["path"] == "docs/readme.txt"
    assert frozen["nested"] == (1, {"ok": True})
    with pytest.raises(TypeError):
        frozen["path"] = "nope"


@pytest.mark.parametrize("value", (float("inf"), float("nan"), {1: "bad"}))
def test_resource_input_rejects_non_json_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        freeze_resource_value(value)


def test_resource_input_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(ValueError, match="cycles"):
        freeze_resource_value(value)


@pytest.mark.asyncio
async def test_in_memory_bridge_reads_the_shared_contract() -> None:
    bridge = InMemoryResourceBridge({"docs/readme.txt": "hello"})
    request = invocation({"path": "docs/readme.txt"})

    assert await bridge.invoke(request) == "hello"
    assert bridge.invocations == [request]


@pytest.mark.parametrize(
    "path",
    (
        "",
        "/absolute.txt",
        "../escape.txt",
        "folder/../escape.txt",
        "folder\\file.txt",
        "C:drive.txt",
        "folder//file.txt",
        "folder/./file.txt",
        "snowman-☃.txt",
    ),
)
@pytest.mark.asyncio
async def test_in_memory_bridge_rejects_nonportable_paths(path: str) -> None:
    bridge = InMemoryResourceBridge({})

    with pytest.raises(ResourceBridgeError) as captured:
        await bridge.invoke(invocation({"path": path}))

    assert captured.value.code is ResourceErrorCode.MALFORMED_INPUT


@pytest.mark.asyncio
async def test_in_memory_bridge_normalizes_missing_and_oversized_results() -> None:
    bridge = InMemoryResourceBridge({"large.txt": "hello"}, max_output_bytes=4)

    with pytest.raises(ResourceBridgeError) as missing:
        await bridge.invoke(invocation({"path": "missing.txt"}))
    with pytest.raises(ResourceBridgeError) as large:
        await bridge.invoke(invocation({"path": "large.txt"}))

    assert missing.value.code is ResourceErrorCode.NOT_FOUND
    assert large.value.code is ResourceErrorCode.LIMIT_EXCEEDED
    assert str(missing.value) == "resource was not found"


def test_resource_audit_event_has_no_payload_field() -> None:
    event = ResourceAuditEvent(
        datetime.now(UTC),
        ResourceInvocationId(1),
        7,
        Principal.parse("human:test"),
        BINDING_ID,
        "read_text",
        ResourceAuditPhase.ADMITTED,
        READ_PERMISSION,
    )

    assert not hasattr(event, "input")
    assert not hasattr(event, "value")
    assert not hasattr(event, "message")
