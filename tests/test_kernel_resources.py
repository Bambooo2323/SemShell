"""Kernel integration tests for the generic Host resource boundary."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from semshell.examples.resource_demo import run_resource_demo
from semshell.kernel import (
    Exit,
    InvokeResource,
    ProcessContext,
    ProcessKernel,
    ProcessState,
    ResourceCompleted,
    ResourceRejected,
    Started,
)
from semshell.resources import (
    InMemoryResourceBridge,
    ResourceAuditPhase,
    ResourceBinding,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceRegistry,
)
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

BINDING_ID = ResourceBindingId("workspace")
READ = Permission("workspace.read_text", "workspace")


class ReaderProgram:
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return InvokeResource(BINDING_ID, "read_text", context.input)
        if isinstance(event, ResourceCompleted):
            return Exit(event.value)
        if isinstance(event, ResourceRejected):
            return Exit(event.error.code)
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


class CancellationResistantBridge:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(self, invocation):  # type: ignore[no-untyped-def]
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await self.release.wait()
        return "late secret"


def make_kernel(bridge: Any, *, capacity: int = 4) -> ProcessKernel:
    descriptor = ResourceBindingDescriptor(
        binding_id=BINDING_ID,
        resource_kind="workspace",
        operations={"read_text": READ},
    )
    catalog = ProcessCatalog()
    catalog.register(
        ProcessImage(
            "reader",
            "1",
            ReaderProgram,
            authority_ceiling=Authority.of((READ,)),
        )
    )
    return ProcessKernel(
        catalog,
        resources=ResourceRegistry((ResourceBinding(descriptor, bridge),)),
        max_resource_invocations=capacity,
    )


async def spawn_reader(kernel: ProcessKernel, value: Any, *, granted: bool = True) -> int:
    await kernel.start()
    return await kernel.spawn(
        ProcessSpec(
            image="reader@1",
            input=value,
            requested_authority=Authority.of((READ,)) if granted else Authority.empty(),
        ),
        principal=Principal("test", "reader"),
    )


@pytest.mark.asyncio
async def test_resource_success_is_authenticated_and_audited() -> None:
    release = asyncio.Event()
    bridge = InMemoryResourceBridge({"notes/a.txt": "hello"}, release=release)
    kernel = make_kernel(bridge)
    pid = await spawn_reader(kernel, {"path": "notes/a.txt"})
    while not bridge.invocations:
        await asyncio.sleep(0)

    invocation = bridge.invocations[0]
    assert invocation.caller_pid == pid
    assert invocation.principal == Principal("test", "reader")
    assert invocation.authority == Authority.of((READ,))
    assert kernel.inspect(pid).pending_resource_invocation_id == invocation.invocation_id
    assert kernel.resource_invocation_count == 1

    release.set()
    result = await kernel.wait(pid)
    assert result.result == "hello"
    assert kernel.resource_invocation_count == 0
    assert [event.phase for event in kernel.resource_audit_events()] == [
        ResourceAuditPhase.ADMITTED,
        ResourceAuditPhase.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_authority_denial_never_calls_bridge() -> None:
    bridge = InMemoryResourceBridge({"a.txt": "secret"})
    kernel = make_kernel(bridge)
    pid = await spawn_reader(kernel, {"path": "a.txt"}, granted=False)

    result = await kernel.wait(pid)
    assert result.result == "resource.authority_denied"
    assert bridge.invocations == []
    audit = kernel.resource_audit_events()
    assert len(audit) == 1
    assert audit[0].phase is ResourceAuditPhase.REJECTED


@pytest.mark.asyncio
async def test_cancellation_suppresses_late_bridge_result_and_retains_capacity() -> None:
    bridge = CancellationResistantBridge()
    kernel = make_kernel(bridge, capacity=1)
    first = await spawn_reader(kernel, {"path": "a.txt"})
    await bridge.started.wait()

    cancelled = await kernel.cancel(first)
    assert cancelled.state is ProcessState.CANCELLED
    assert kernel.resource_invocation_count == 1

    second = await spawn_reader(kernel, {"path": "a.txt"})
    second_result = await kernel.wait(second)
    assert second_result.result == "resource.capacity_exceeded"

    bridge.release.set()
    while kernel.resource_invocation_count:
        await asyncio.sleep(0)
    assert kernel.inspect(first).state is ProcessState.CANCELLED
    phases = [event.phase for event in kernel.resource_audit_events()]
    assert ResourceAuditPhase.CANCELLED in phases
    assert ResourceAuditPhase.LATE_COMPLETED in phases


@pytest.mark.asyncio
async def test_resource_cancelled_before_first_step_releases_capacity() -> None:
    class NeverStartedBridge:
        def __init__(self) -> None:
            self.invocations = 0

        async def invoke(self, invocation):  # type: ignore[no-untyped-def]
            self.invocations += 1
            await asyncio.Event().wait()

    bridge = NeverStartedBridge()
    kernel = make_kernel(bridge, capacity=1)
    first = await spawn_reader(kernel, {"path": "a.txt"})
    while kernel.inspect(first).state is not ProcessState.WAITING:
        await asyncio.sleep(0)

    cancelled = await kernel.cancel(first)
    for _ in range(100):
        if kernel.resource_invocation_count == 0:
            break
        await asyncio.sleep(0)

    assert cancelled.state is ProcessState.CANCELLED
    assert kernel.resource_invocation_count == 0
    assert bridge.invocations == 0
    await kernel.stop()


@pytest.mark.asyncio
async def test_unexpected_bridge_failure_is_sanitized() -> None:
    class BrokenBridge:
        async def invoke(self, invocation):  # type: ignore[no-untyped-def]
            raise RuntimeError("host path and secret")

    kernel = make_kernel(BrokenBridge())
    pid = await spawn_reader(kernel, {"path": "a.txt"})
    result = await kernel.wait(pid)

    assert result.result == "resource.bridge_failure"
    audit = kernel.resource_audit_events()
    assert all(not hasattr(event, "payload") for event in audit)
    assert "secret" not in repr(audit)


@pytest.mark.asyncio
async def test_resource_demo_uses_the_in_memory_bridge() -> None:
    fake = await run_resource_demo(
        InMemoryResourceBridge({"note.txt": "same result"}), "note.txt"
    )
    denied_bridge = InMemoryResourceBridge({"note.txt": "hidden"})
    denied = await run_resource_demo(
        denied_bridge, "note.txt", grant_authority=False
    )
    escaped = await run_resource_demo(InMemoryResourceBridge({}), "../outside.txt")

    assert fake.result == "same result"
    assert denied.result == {"error": "resource.authority_denied"}
    assert denied_bridge.invocations == []
    assert escaped.result == {"error": "resource.malformed_input"}
