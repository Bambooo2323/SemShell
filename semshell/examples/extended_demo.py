"""Extended offline evidence for identity, authority, and lifecycle boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from semshell.examples.resource_demo import (
    WORKSPACE_BINDING,
    WORKSPACE_READ,
    WorkspaceReaderProgram,
    run_resource_demo,
)
from semshell.host import HostAdmin
from semshell.kernel import (
    ChildrenCompleted,
    Exit,
    MessageReceived,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    ProcessState,
    Send,
    Spawn,
    Spawned,
    Started,
    Wait,
    Yield,
)
from semshell.kernel.kernel import ProcessKernel
from semshell.resources import (
    InMemoryResourceBridge,
    ResourceAuditPhase,
    ResourceBinding,
    ResourceBindingDescriptor,
    ResourceInvocation,
    ResourceRegistry,
)
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

DEMO_PRINCIPAL = Principal.parse("human:extended-demo")


@dataclass(frozen=True, slots=True)
class IPCDemoEvidence:
    sender_pid: int
    observed_source_pid: int
    receiver_pid: int
    payload: Any


@dataclass(frozen=True, slots=True)
class ResourceDemoEvidence:
    required_permission: Permission
    success_result: Any
    success_invocations: int
    success_phases: tuple[ResourceAuditPhase, ...]
    denied_result: Any
    denied_invocations: int
    denied_phases: tuple[ResourceAuditPhase, ...]


@dataclass(frozen=True, slots=True)
class CancellationDemoEvidence:
    owner_pid: int
    child_pid: int
    child_owner_pid: int | None
    owner_state: ProcessState
    child_state: ProcessState
    child_result_publications: int
    late_outcome_suppressed: bool
    resource_phases: tuple[ResourceAuditPhase, ...]


@dataclass(frozen=True, slots=True)
class ExtendedDemoReport:
    ipc: IPCDemoEvidence
    resource: ResourceDemoEvidence
    cancellation: CancellationDemoEvidence


class MessageReceiverProgram:
    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            return Yield()
        if isinstance(event, MessageReceived):
            return Exit(
                {
                    "source_pid": event.message.source_pid,
                    "target_pid": event.message.target_pid,
                    "payload": event.message.payload,
                }
            )
        raise RuntimeError(f"unsupported receiver event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class MessageSenderProgram:
    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if not isinstance(context.input, dict):
                raise TypeError("sender input must be a mapping")
            return Send(context.input["target_pid"], context.input["payload"])
        raise RuntimeError(f"unsupported sender event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class ResourceOwnerProgram:
    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            return Spawn(
                (
                    ProcessSpec(
                        image="demo.blocked-reader@1",
                        input={"binding_id": str(WORKSPACE_BINDING), "path": "late.txt"},
                        requested_authority=Authority.of((WORKSPACE_READ,)),
                    ),
                )
            )
        if isinstance(event, Spawned):
            return Wait(event.pids)
        if isinstance(event, ChildrenCompleted):
            return Exit(event.results[0].result)
        raise RuntimeError(f"unsupported owner event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class CancellationResistantBridge:
    """Complete after cancellation so the Kernel must suppress the late value."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(self, invocation: ResourceInvocation) -> object:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await self.release.wait()
        return "late value"


async def _run_ipc_demo() -> IPCDemoEvidence:
    catalog = ProcessCatalog()
    catalog.register(ProcessImage("demo.receiver", "1", MessageReceiverProgram))
    catalog.register(ProcessImage("demo.sender", "1", MessageSenderProgram))
    admin = HostAdmin(ProcessKernel(catalog))
    await admin.start()
    try:
        receiver_pid = await admin.spawn(
            ProcessSpec(image="demo.receiver@1"), DEMO_PRINCIPAL, None
        )
        sender_pid = await admin.spawn(
            ProcessSpec(
                image="demo.sender@1",
                input={
                    "target_pid": receiver_pid,
                    "payload": "kernel-authenticated",
                },
            ),
            DEMO_PRINCIPAL,
            None,
        )
        result = await admin.wait(receiver_pid)
        if not isinstance(result.result, Mapping):
            raise TypeError("receiver produced an invalid demonstration result")
        return IPCDemoEvidence(
            sender_pid=sender_pid,
            observed_source_pid=result.result["source_pid"],
            receiver_pid=result.result["target_pid"],
            payload=result.result["payload"],
        )
    finally:
        await admin.stop()


async def _run_resource_demo() -> ResourceDemoEvidence:
    success_bridge = InMemoryResourceBridge({"notes/demo.txt": "hello"})
    success = await run_resource_demo(success_bridge, "notes/demo.txt")
    denied_bridge = InMemoryResourceBridge({"notes/demo.txt": "secret"})
    denied = await run_resource_demo(
        denied_bridge, "notes/demo.txt", grant_authority=False
    )
    return ResourceDemoEvidence(
        required_permission=WORKSPACE_READ,
        success_result=success.result,
        success_invocations=len(success_bridge.invocations),
        success_phases=tuple(item.phase for item in success.audit),
        denied_result=denied.result,
        denied_invocations=len(denied_bridge.invocations),
        denied_phases=tuple(item.phase for item in denied.audit),
    )


async def _run_cancellation_demo() -> CancellationDemoEvidence:
    bridge = CancellationResistantBridge()
    descriptor = ResourceBindingDescriptor(
        WORKSPACE_BINDING,
        "workspace",
        {"read_text": WORKSPACE_READ},
    )
    catalog = ProcessCatalog()
    catalog.register(
        ProcessImage(
            "demo.blocked-reader",
            "1",
            WorkspaceReaderProgram,
            authority_ceiling=Authority.of((WORKSPACE_READ,)),
        )
    )
    catalog.register(
        ProcessImage(
            "demo.resource-owner",
            "1",
            ResourceOwnerProgram,
            required_capabilities=("demo.blocked-reader",),
            authority_ceiling=Authority.of((WORKSPACE_READ,)),
        )
    )
    kernel = ProcessKernel(
        catalog,
        resources=ResourceRegistry((ResourceBinding(descriptor, bridge),)),
    )
    admin = HostAdmin(kernel)
    await admin.start()
    try:
        owner_pid = await admin.spawn(
            ProcessSpec(
                image="demo.resource-owner@1",
                requested_authority=Authority.of((WORKSPACE_READ,)),
            ),
            DEMO_PRINCIPAL,
            None,
        )
        await bridge.started.wait()
        child_pid = admin.inspect(owner_pid).child_pids[0]
        owner_result = await admin.cancel(owner_pid, "extended demo cancellation")
        child_result = await admin.wait(child_pid)
        bridge.release.set()

        async def wait_for_resource_drain() -> None:
            while kernel.resource_invocation_count:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_resource_drain(), timeout=1.0)
        phases = tuple(item.phase for item in kernel.resource_audit_events())
        child_snapshot = admin.inspect(child_pid)
        return CancellationDemoEvidence(
            owner_pid=owner_pid,
            child_pid=child_pid,
            child_owner_pid=child_snapshot.owner_pid,
            owner_state=owner_result.state,
            child_state=child_result.state,
            child_result_publications=int(child_snapshot.result is not None),
            late_outcome_suppressed=(
                child_snapshot.result == child_result
                and child_result.state is ProcessState.CANCELLED
                and child_result.result != "late value"
                and ResourceAuditPhase.LATE_COMPLETED in phases
            ),
            resource_phases=phases,
        )
    finally:
        bridge.release.set()
        await admin.stop()


async def run_extended_demo() -> ExtendedDemoReport:
    """Run all extended architecture evidence without external resources."""

    return ExtendedDemoReport(
        ipc=await _run_ipc_demo(),
        resource=await _run_resource_demo(),
        cancellation=await _run_cancellation_demo(),
    )
