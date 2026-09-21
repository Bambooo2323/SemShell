"""Offline dialogue, delegated authority, and concurrent work on the guest ABI.

The scripted models deliberately probe forbidden operations for demonstration.
The persistent UserShell approves one allowlisted delegation from its existing
Authority; it never raises llm1's Authority or invokes Kernel administration.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from semshell.examples.reporting import project_authority, project_public_value
from semshell.host import ConsoleBridge
from semshell.kernel import (
    ChildrenCompleted,
    ConsoleInput,
    Exit,
    Fail,
    InvokeResource,
    MessageReceived,
    OperationRejected,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    ProcessKernel,
    ProcessState,
    ResourceCompleted,
    ResourceRejected,
    Send,
    Spawn,
    Spawned,
    Started,
    Wait,
    Yield,
)
from semshell.llm import LLMRequest, ScriptedSemanticBackend, SemanticBackend
from semshell.resources import (
    InMemoryResourceBridge,
    ResourceBinding,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceRegistry,
)
from semshell.security import Authority, DefaultPolicy, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

REPORT_BINDING = ResourceBindingId("delegation.report")
OTHER_BINDING = ResourceBindingId("delegation.other")
REPORT_READ = Permission("workspace.read_text", str(REPORT_BINDING))
REPORT_AUTHORITY = Authority.of((REPORT_READ,))
REQUEST_ID = "report-review"
DEFAULT_DIALOGUE = "Review alpha beta and include the restricted project report."


@dataclass
class DemoEvidence:
    """Host-injected diagnostics and a deterministic concurrency fixture.

    No guest gets a Kernel reference. The gate keeps tool work pending until
    the approval decision (or delegated worker start), without timing sleeps.
    """

    trace: list[dict[str, Any]] = field(default_factory=list)
    tools_running: set[int] = field(default_factory=set)
    tools_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_tools: asyncio.Event = field(default_factory=asyncio.Event)
    llm1_created: asyncio.Event = field(default_factory=asyncio.Event)
    llm1_pid: int | None = None

    def record(self, event: str, pid: int, **details: Any) -> None:
        self.trace.append({"event": event, "pid": pid, **details})


class ParallelTextTool:
    def __init__(self, evidence: DemoEvidence) -> None:
        self.evidence = evidence

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if not isinstance(event, Started) or not isinstance(context.input, dict):
            return Fail("invalid tool input or event")
        text = context.input["text"]
        operation = context.input["operation"]
        if not isinstance(text, str) or operation not in {"words", "characters"}:
            return Fail("unsupported text operation")
        self.evidence.tools_running.add(context.pid)
        self.evidence.record("tool_started", context.pid, operation=operation)
        if len(self.evidence.tools_running) == 2:
            self.evidence.tools_started.set()
        try:
            await self.evidence.release_tools.wait()
            value = len(text.split()) if operation == "words" else len(text)
            self.evidence.record("tool_completed", context.pid)
            return Exit({"operation": operation, "value": value})
        finally:
            self.evidence.tools_running.discard(context.pid)

    async def stop(self, reason: str) -> None:
        return None


class DelegatingLLM:
    """Plan, demonstrate denied access, request delegation, then aggregate."""

    def __init__(self, backend: SemanticBackend, evidence: DemoEvidence) -> None:
        self.backend = backend
        self.evidence = evidence
        self.phase = "new"
        self.tools: tuple[int, ...] = ()
        self.plan: dict[str, Any] = {}
        self.delegation: Any = None

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            response = await self.backend.generate(
                LLMRequest(
                    model="scripted",
                    input=context.input,
                    instructions="Plan a report review. Return a delegation JSON request.",
                )
            )
            plan = json.loads(response.output_text)
            if (
                not isinstance(plan, dict)
                or plan.get("kind") != "request_delegation"
                or not isinstance(plan.get("reason"), str)
                or not plan["reason"]
            ):
                return Fail("invalid delegation plan")
            self.plan = plan
            self.phase = "tools"
            return Spawn(
                tuple(
                    ProcessSpec(
                        image="delegation.text-tool@1",
                        input={"text": context.input, "operation": operation},
                    )
                    for operation in ("words", "characters")
                )
            )
        if isinstance(event, Spawned) and self.phase == "tools":
            self.tools = event.pids
            self.phase = "probe_resource"
            return InvokeResource(REPORT_BINDING, "read_text", {"path": "report.txt"})
        if isinstance(event, ResourceRejected) and self.phase == "probe_resource":
            if event.error.code != "resource.authority_denied":
                return Fail(event.error)
            self.evidence.record("llm1_read_denied", context.pid, code=event.error.code)
            self.phase = "probe_spawn"
            # Intentionally invalid: a child cannot exceed this parent's Authority.
            return Spawn(
                (
                    ProcessSpec(
                        image="delegation.llm2@1",
                        requested_authority=REPORT_AUTHORITY,
                    ),
                )
            )
        if isinstance(event, OperationRejected) and self.phase == "probe_spawn":
            if event.operation != "spawn":
                return Fail(event.error)
            self.evidence.record(
                "llm1_spawn_denied", context.pid, code=event.error.code
            )
            self.phase = "delegation"
            if context.owner_pid is None:
                return Fail("llm1 requires a UserShell owner")
            return Send(context.owner_pid, self.plan)
        if isinstance(event, MessageReceived) and self.phase == "delegation":
            payload = event.message.payload
            if (
                event.message.source_pid != context.owner_pid
                or not isinstance(payload, Mapping)
                or payload.get("request_id") != REQUEST_ID
                or payload.get("kind") != "delegation_result"
            ):
                self.evidence.record("reply_ignored", context.pid)
                return Yield()
            self.delegation = payload
            self.phase = "waiting_tools"
            return Wait(self.tools)
        if isinstance(event, ChildrenCompleted) and self.phase == "waiting_tools":
            if any(item.state is not ProcessState.EXITED for item in event.results):
                return Fail("a parallel tool did not complete successfully")
            tool_results = [item.result for item in event.results]
            response = await self.backend.generate(
                LLMRequest(
                    model="scripted",
                    input={"tools": tool_results, "delegation": self.delegation},
                    instructions="Summarize available results, including denied delegation.",
                )
            )
            self.phase = "complete"
            return Exit(
                {
                    "summary": response.output_text,
                    "tools": tool_results,
                    "delegation": self.delegation,
                }
            )
        return Fail(f"unexpected llm1 event in {self.phase}: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class RestrictedLLM:
    """Read the approved binding, demonstrate scope denial, then analyze."""

    def __init__(self, backend: SemanticBackend, evidence: DemoEvidence) -> None:
        self.backend = backend
        self.evidence = evidence
        self.report: Any = None
        self.phase = "new"

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            self.evidence.record(
                "llm2_started",
                context.pid,
                tools_running=sorted(self.evidence.tools_running),
            )
            self.evidence.release_tools.set()
            self.phase = "read"
            return InvokeResource(REPORT_BINDING, "read_text", {"path": "report.txt"})
        if isinstance(event, ResourceCompleted) and self.phase == "read":
            self.report = event.value
            self.phase = "probe_scope"
            return InvokeResource(OTHER_BINDING, "read_text", {"path": "other.txt"})
        if isinstance(event, ResourceRejected) and self.phase == "probe_scope":
            if event.error.code != "resource.authority_denied":
                return Fail(event.error)
            self.evidence.record(
                "llm2_scope_denied", context.pid, code=event.error.code
            )
            response = await self.backend.generate(
                LLMRequest(
                    model="scripted",
                    input={"task": context.input, "report": self.report},
                    instructions="Analyze only the authorized project report.",
                )
            )
            self.phase = "complete"
            return Exit(
                {"analysis": response.output_text, "scope_denial": event.error.code}
            )
        return Fail(f"unexpected llm2 event in {self.phase}: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class DelegationUserShell:
    """One-dialogue shell with a fixed, offline approval policy and allowlist.

    It remains open after replying. Approval is a user-space decision; Kernel
    admission independently enforces the shell's existing Authority.
    """

    def __init__(self, evidence: DemoEvidence, *, approve: bool = True) -> None:
        self.evidence = evidence
        self.approve = approve
        self.llm1_pid: int | None = None
        self.llm2_pid: int | None = None
        self.phase = "idle"

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            return Yield()
        if isinstance(event, ConsoleInput) and self.phase == "idle":
            if event.principal != context.principal or not isinstance(
                event.payload, str
            ):
                return Fail("invalid dialogue input")
            self.phase = "starting_llm1"
            self.evidence.record("dialogue", context.pid, text=event.payload)
            return Spawn((ProcessSpec(image="delegation.llm1@1", input=event.payload),))
        if isinstance(event, Spawned) and self.phase == "starting_llm1":
            self.llm1_pid = event.pids[0]
            self.evidence.llm1_pid = self.llm1_pid
            self.evidence.llm1_created.set()
            self.phase = "request"
            return Yield()
        if isinstance(event, MessageReceived) and self.phase == "request":
            if event.message.source_pid != self.llm1_pid:
                self.evidence.record("request_ignored", context.pid)
                return Yield()
            request = event.message.payload
            valid = (
                isinstance(request, Mapping)
                and set(request) == {"kind", "request_id", "binding_id", "reason"}
                and request.get("kind") == "request_delegation"
                and request.get("request_id") == REQUEST_ID
                and request.get("binding_id") == str(REPORT_BINDING)
                and isinstance(request.get("reason"), str)
                and bool(request.get("reason"))
            )
            await self.evidence.tools_started.wait()
            allowed = valid and self.approve
            self.evidence.record(
                "approval",
                context.pid,
                requester_pid=event.message.source_pid,
                allowed=allowed,
                request=project_public_value(request),
                tools_running=sorted(self.evidence.tools_running),
            )
            if not allowed:
                self.evidence.release_tools.set()
                self.phase = "replied"
                return Send(
                    event.message.source_pid,
                    {
                        "kind": "delegation_result",
                        "request_id": REQUEST_ID,
                        "status": "denied",
                        "reason": "approval declined or request outside allowlist",
                    },
                )
            self.phase = "starting_llm2"
            return Spawn(
                (
                    ProcessSpec(
                        image="delegation.llm2@1",
                        input={"request_id": REQUEST_ID, "task": request["reason"]},
                        requested_authority=REPORT_AUTHORITY,
                    ),
                )
            )
        if isinstance(event, Spawned) and self.phase == "starting_llm2":
            self.llm2_pid = event.pids[0]
            self.phase = "waiting_llm2"
            return Wait(event.pids)
        if isinstance(event, OperationRejected) and self.phase == "starting_llm2":
            self.evidence.release_tools.set()
            return self._reply({"status": "denied", "reason": event.error.message})
        if isinstance(event, ChildrenCompleted) and self.phase == "waiting_llm2":
            result = event.results[0]
            return self._reply(
                {
                    "status": "completed"
                    if result.state is ProcessState.EXITED
                    else "failed",
                    "worker_pid": result.pid,
                    "result": result.result,
                    "error": result.error.code if result.error else None,
                }
            )
        return Fail(
            f"unexpected UserShell event in {self.phase}: {type(event).__name__}"
        )

    def _reply(self, payload: dict[str, Any]) -> Send:
        if self.llm1_pid is None:
            raise RuntimeError("no requester")
        self.phase = "replied"
        return Send(
            self.llm1_pid,
            {
                "kind": "delegation_result",
                "request_id": REQUEST_ID,
                **payload,
            },
        )

    async def stop(self, reason: str) -> None:
        return None


async def run_delegation_demo(
    *,
    approve: bool = True,
    dialogue: str = DEFAULT_DIALOGUE,
    requested_binding: str = str(REPORT_BINDING),
    shell_authority: Authority = REPORT_AUTHORITY,
) -> dict[str, Any]:
    """Run one bounded offline conversation and report pre-shutdown evidence."""
    evidence = DemoEvidence()
    llm1 = ScriptedSemanticBackend(
        (
            json.dumps(
                {
                    "kind": "request_delegation",
                    "request_id": REQUEST_ID,
                    "binding_id": requested_binding,
                    "reason": "Analyze the project report while text statistics run.",
                }
            ),
            "Review assembled from text statistics and the delegation outcome.",
        )
    )
    llm2 = ScriptedSemanticBackend(
        ("The authorized report says the project is on track.",)
    )
    catalog = ProcessCatalog()
    catalog.register(
        ProcessImage(
            "delegation.usershell",
            "1",
            lambda: DelegationUserShell(evidence, approve=approve),
            authority_ceiling=REPORT_AUTHORITY,
        )
    )
    catalog.register(
        ProcessImage(
            "delegation.llm1",
            "1",
            lambda: DelegatingLLM(llm1, evidence),
            authority_ceiling=Authority.empty(),
        )
    )
    catalog.register(
        ProcessImage(
            "delegation.llm2",
            "1",
            lambda: RestrictedLLM(llm2, evidence),
            authority_requirements=REPORT_AUTHORITY,
            authority_ceiling=REPORT_AUTHORITY,
        )
    )
    catalog.register(
        ProcessImage(
            "delegation.text-tool",
            "1",
            lambda: ParallelTextTool(evidence),
            authority_ceiling=Authority.empty(),
        )
    )
    report_bridge = InMemoryResourceBridge({"report.txt": "Project status: on track."})
    other_bridge = InMemoryResourceBridge({"other.txt": "Unrelated private material."})
    resources = ResourceRegistry(
        tuple(
            ResourceBinding(
                ResourceBindingDescriptor(
                    binding,
                    "workspace",
                    {
                        "read_text": Permission("workspace.read_text", str(binding)),
                    },
                ),
                bridge,
            )
            for binding, bridge in (
                (REPORT_BINDING, report_bridge),
                (OTHER_BINDING, other_bridge),
            )
        )
    )
    kernel = ProcessKernel(
        catalog,
        resources=resources,
        policy=DefaultPolicy(system_authority=REPORT_AUTHORITY),
    )
    principal = Principal.parse("human:delegation-demo")
    await kernel.start()
    try:
        async with asyncio.timeout(5):
            shell_pid = await kernel.spawn(
                ProcessSpec(
                    image="delegation.usershell@1", requested_authority=shell_authority
                ),
                principal=principal,
                authority_ceiling=REPORT_AUTHORITY,
            )
            await ConsoleBridge(kernel, shell_pid, principal).write_input(dialogue)
            await evidence.llm1_created.wait()
            if evidence.llm1_pid is None:
                raise RuntimeError("UserShell did not create llm1")
            result = await kernel.wait(evidence.llm1_pid)
            if result.state is not ProcessState.EXITED:
                raise RuntimeError(f"llm1 failed: {result.error}")
            return {
                "scenario": "delegation",
                "backend": "scripted",
                "approval_policy": "allow_report" if approve else "decline",
                "result": project_public_value(result.result),
                "trace": evidence.trace,
                "tree": [
                    {
                        "pid": item.pid,
                        "owner_pid": item.owner_pid,
                        "image": item.image_id,
                        "state": item.state.value,
                        "authority": project_authority(item.authority),
                    }
                    for item in kernel.tree(shell_pid)
                ],
                "authority_decisions": [
                    {
                        "requester_pid": item.requester_pid,
                        "image": item.image_reference,
                        "decision": item.decision.value,
                        "reason": item.reason,
                        "requested": project_authority(item.requested_authority),
                        "granted": project_authority(item.granted_authority),
                    }
                    for item in kernel.authority_decisions()
                ],
                "resource_audit": [
                    {
                        "caller_pid": item.caller_pid,
                        "binding": str(item.binding_id),
                        "phase": item.phase.value,
                        "error": item.error_code.value if item.error_code else None,
                    }
                    for item in kernel.resource_audit_events()
                ],
                "bridge_invocations": {
                    "report": len(report_bridge.invocations),
                    "other": len(other_bridge.invocations),
                },
                "model_calls": {"llm1": len(llm1.requests), "llm2": len(llm2.requests)},
            }
    finally:
        evidence.release_tools.set()
        await kernel.stop()
