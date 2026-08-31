"""Minimal guest proof for the generic Host resource bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semshell.kernel import (
    Exit,
    InvokeResource,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    ProcessKernel,
    ResourceCompleted,
    ResourceRejected,
    Started,
)
from semshell.resources import (
    HostResourceBridge,
    ResourceAuditEvent,
    ResourceBinding,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceRegistry,
)
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

WORKSPACE_BINDING = ResourceBindingId("demo.workspace")
WORKSPACE_READ = Permission("workspace.read_text", str(WORKSPACE_BINDING))


class WorkspaceReaderProgram:
    """Read one portable guest path without knowing the bridge implementation."""

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if not isinstance(context.input, dict):
                raise TypeError("workspace-reader input must be a mapping")
            binding = context.input.get("binding_id")
            path = context.input.get("path")
            if not isinstance(binding, str):
                raise TypeError("binding_id must be a string")
            return InvokeResource(
                ResourceBindingId(binding), "read_text", {"path": path}
            )
        if isinstance(event, ResourceCompleted):
            return Exit(event.value)
        if isinstance(event, ResourceRejected):
            return Exit({"error": event.error.code})
        raise RuntimeError(
            f"unsupported WorkspaceReader event: {type(event).__name__}"
        )

    async def stop(self, reason: str) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ResourceDemoReport:
    """Guest result plus payload-free resource audit evidence."""

    result: Any
    audit: tuple[ResourceAuditEvent, ...]


async def run_resource_demo(
    bridge: HostResourceBridge,
    path: str,
    *,
    grant_authority: bool = True,
) -> ResourceDemoReport:
    """Run the unchanged workspace-reader against one Host bridge."""

    descriptor = ResourceBindingDescriptor(
        WORKSPACE_BINDING,
        "workspace",
        {"read_text": WORKSPACE_READ},
    )
    catalog = ProcessCatalog()
    catalog.register(
        ProcessImage(
            "demo.workspace-reader",
            "1",
            WorkspaceReaderProgram,
            authority_ceiling=Authority.of((WORKSPACE_READ,)),
        )
    )
    kernel = ProcessKernel(
        catalog,
        resources=ResourceRegistry((ResourceBinding(descriptor, bridge),)),
    )
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(
            image="demo.workspace-reader@1",
            input={"binding_id": str(WORKSPACE_BINDING), "path": path},
            requested_authority=(
                Authority.of((WORKSPACE_READ,))
                if grant_authority
                else Authority.empty()
            ),
        ),
        principal=Principal.parse("human:resource-demo"),
    )
    result = await kernel.wait(pid)
    report = ResourceDemoReport(result.result, kernel.resource_audit_events())
    await kernel.stop()
    return report
