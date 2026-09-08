"""In-process event-driven SemShell process kernel."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from semshell.kernel._runtime import (
    ProcessControlBlock,
    ResourceTaskRecord,
    TerminalDecision,
)
from semshell.kernel.actions import (
    Cancel,
    Detach,
    DiscoverImages,
    Exit,
    Fail,
    InvokeResource,
    ProcessAction,
    Send,
    Spawn,
    Wait,
    Yield,
)
from semshell.kernel.errors import (
    ApprovalRequired,
    InvalidAction,
    InvalidKernelState,
    KernelNotRunning,
    OperationDenied,
    ProcessNotFound,
)
from semshell.kernel.events import (
    ChildrenCompleted,
    ConsoleInput,
    ImagesDiscovered,
    Message,
    MessageKind,
    MessageReceived,
    OperationCompleted,
    OperationRejected,
    ResourceCompleted,
    ResourceRejected,
    Spawned,
    Started,
)
from semshell.kernel.process import (
    COMPLETION_STATES,
    TERMINAL_STATES,
    CancelMode,
    ErrorOrigin,
    OwnershipMode,
    ProcessContext,
    ProcessError,
    ProcessResult,
    ProcessSnapshot,
    ProcessState,
    WaitMode,
)
from semshell.resources.bridge import HostResourceBridge, ResourceBridgeError
from semshell.resources.registry import ResourceRegistry
from semshell.resources.types import (
    ResourceAuditEvent,
    ResourceAuditPhase,
    ResourceBindingDescriptor,
    ResourceErrorCode,
    ResourceInvocation,
    ResourceInvocationId,
    freeze_resource_value,
)
from semshell.security.audit import AuthorityDecisionRecord
from semshell.security.authority import Authority, Permission
from semshell.security.policy import (
    AdmissionDecision,
    AdmissionRequest,
    DefaultPolicy,
    Policy,
)
from semshell.security.principal import Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessImageDescriptor, ProcessSpec
from semshell.software.program import ProcessProgram
from semshell.values import freeze_public_value

logger = logging.getLogger(__name__)


class KernelState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"


class ProcessKernel:
    """Own process identity, scheduling, IPC, and lifecycle."""

    def __init__(
        self,
        catalog: ProcessCatalog | None = None,
        *,
        max_running: int = 4,
        max_processes: int = 1000,
        cancellation_timeout: float = 1.0,
        policy: Policy | None = None,
        resources: ResourceRegistry | None = None,
        max_resource_invocations: int = 4,
    ) -> None:
        if max_running < 1 or max_processes < 1 or max_resource_invocations < 1:
            raise ValueError("process limits must be positive")
        if cancellation_timeout <= 0:
            raise ValueError("cancellation_timeout must be positive")
        self.catalog = catalog or ProcessCatalog()
        self.max_running = max_running
        self.max_processes = max_processes
        self.cancellation_timeout = cancellation_timeout
        self.policy = policy or DefaultPolicy()
        self.resources = resources or ResourceRegistry()
        self.max_resource_invocations = max_resource_invocations
        self._state = KernelState.STOPPED
        self._lifecycle_lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[None] | None = None
        self._decision_lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max_running)
        self._processes: dict[int, ProcessControlBlock] = {}
        self._reserved_pids: set[int] = set()
        self._next_pid = 1
        self._tasks: set[asyncio.Task[None]] = set()
        self._draining_tasks: set[asyncio.Task[Any]] = set()
        self._running_count = 0
        self._authority_audit: list[AuthorityDecisionRecord] = []
        self._next_resource_invocation_id = 1
        self._resource_tasks: dict[ResourceInvocationId, ResourceTaskRecord] = {}
        self._resource_in_flight = 0
        self._resource_audit: list[ResourceAuditEvent] = []
        self.peak_running = 0

    @property
    def state(self) -> KernelState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state is KernelState.RUNNING

    @property
    def process_count(self) -> int:
        return len(self._processes)

    @property
    def draining_task_count(self) -> int:
        """Return non-cooperative cleanup tasks retained for observation."""

        return len(self._draining_tasks)

    def authority_decisions(self) -> tuple[AuthorityDecisionRecord, ...]:
        """Return immutable authority decisions in evaluation order."""

        return tuple(self._authority_audit)

    @property
    def resource_invocation_count(self) -> int:
        """Return the number of bridge tasks whose capacity slot is live."""

        return self._resource_in_flight

    def resource_audit_events(self) -> tuple[ResourceAuditEvent, ...]:
        """Return immutable resource audit phases in append order."""

        return tuple(self._resource_audit)

    def list_resource_bindings(self) -> tuple[ResourceBindingDescriptor, ...]:
        """Return startup-fixed Host resource descriptors for diagnostics."""

        return self.resources.descriptors()

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._state is KernelState.RUNNING:
                return
            if self._state is KernelState.STOPPING:
                raise InvalidKernelState("cannot start a stopping kernel")
            self._shutdown_task = None
            self._state = KernelState.RUNNING

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self._state is KernelState.STOPPED:
                return
            if self._shutdown_task is None:
                self._state = KernelState.STOPPING
                roots = tuple(
                    pcb
                    for pcb in self._processes.values()
                    if pcb.context.owner_pid is None
                    and pcb.state not in TERMINAL_STATES
                )
                # A running activation may still detach a child while an earlier
                # root is cleaning up. Keep all admitted identities as a fallback.
                children = tuple(
                    pcb for pcb in self._processes.values()
                    if pcb.context.owner_pid is not None
                    and pcb.state not in TERMINAL_STATES
                )
                self._shutdown_task = asyncio.create_task(
                    self._shutdown(roots + children)
                )
                self._shutdown_task.add_done_callback(self._observe_task)
            shutdown = self._shutdown_task
        await asyncio.shield(shutdown)

    @staticmethod
    def _observe_task(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _shutdown(self, targets: tuple[ProcessControlBlock, ...]) -> None:
        for root in targets:
            await self._cancel_tree_after_failures(
                root, reason="kernel stopped"
            )
        await self._drain_finished_tasks()
        async with self._lifecycle_lock:
            self._state = KernelState.STOPPED

    def register_image(self, image: ProcessImage) -> None:
        """Load one immutable exact image definition into the live Catalog."""

        self.catalog.register(image)

    def unregister_image(self, reference: str) -> ProcessImageDescriptor:
        """Unload an exact image only when no live-table Process uses it."""

        if any(
            f"{pcb.context.image_id}@{pcb.context.image_version}" == reference
            for pcb in self._processes.values()
        ):
            raise OperationDenied(f"process image is still in use: {reference}")
        return self.catalog.unregister(reference).describe()

    def list_images(self) -> tuple[ProcessImageDescriptor, ...]:
        """Return deterministic factory-free image descriptions."""

        return tuple(image.describe() for image in self.catalog.list_images())

    def resolve_image(
        self,
        *,
        image: str | None = None,
        capability: str | None = None,
        provider: str | None = None,
    ) -> ProcessImageDescriptor:
        """Resolve an exact image or capability to a factory-free description."""

        return self.catalog.resolve(
            image=image, capability=capability, provider=provider
        ).describe()

    async def spawn(
        self,
        spec: ProcessSpec,
        *,
        principal: Principal,
        parent_pid: int | None = None,
        authority_ceiling: Authority | None = None,
    ) -> int:
        """Atomically admit one process through the trusted Python boundary."""

        return (
            await self.spawn_many(
                (spec,),
                principal=principal,
                parent_pid=parent_pid,
                authority_ceiling=authority_ceiling,
            )
        )[0]

    async def spawn_many(
        self,
        specs: tuple[ProcessSpec, ...],
        *,
        principal: Principal,
        parent_pid: int | None = None,
        authority_ceiling: Authority | None = None,
    ) -> tuple[int, ...]:
        """Atomically admit processes without exposing Process Table internals."""

        self._require_running()
        if not specs:
            raise ValueError("spawn_many requires at least one process specification")
        return self._admit_many(
            tuple(specs),
            principal=principal,
            parent_pid=parent_pid,
            authority_ceiling=authority_ceiling,
        )

    async def send(
        self,
        target_pid: int,
        payload: Any,
        *,
        source_pid: int,
        kind: MessageKind = MessageKind.EVENT,
        correlation_id: str | None = None,
    ) -> None:
        self._require_running()
        self._deliver_message(
            Message(
                source_pid=source_pid,
                target_pid=target_pid,
                kind=kind,
                payload=payload,
                correlation_id=correlation_id,
            )
        )

    async def deliver_console_input(
        self, target_pid: int, payload: Any, *, principal: Principal
    ) -> None:
        """Deliver input through a Host bridge already bound to ``target_pid``."""

        self._require_running()
        target = self._get_process(target_pid)
        if target.state in TERMINAL_STATES | {
            ProcessState.CANCELLING,
            ProcessState.FAILING,
        }:
            raise InvalidKernelState(
                f"process {target.pid} cannot accept external input"
            )
        target.mailbox.append(ConsoleInput(principal, payload))
        if (
            target.state is ProcessState.WAITING
            and target.waiting_for is None
            and target.operation_completion is None
            and target.pending_resource_invocation_id is None
        ):
            target.state = ProcessState.READY
            self._schedule(target)

    async def wait(self, pid: int, timeout: float | None = None) -> ProcessResult:
        completion = asyncio.shield(self._get_process(pid).completion)
        return (
            await completion
            if timeout is None
            else await asyncio.wait_for(completion, timeout)
        )

    async def cancel(
        self, pid: int, *, mode: CancelMode = CancelMode.SELF, reason: str = "cancelled"
    ) -> ProcessResult:
        if not reason:
            raise ValueError("cancellation reason must not be empty")
        pcb = self._get_process(pid)
        self._request_cancel(pcb, mode=mode, reason=reason)
        return await asyncio.shield(pcb.completion)

    def _request_cancel(
        self, pcb: ProcessControlBlock, *, mode: CancelMode, reason: str
    ) -> None:
        """Validate and register the whole accepted cancellation without yielding."""

        if not reason:
            raise ValueError("cancellation reason must not be empty")
        if pcb.result is not None:
            return
        if pcb.decision is not None:
            if pcb.decision.state is ProcessState.FAILED:
                raise OperationDenied("an abnormal failure decision already won")
            return
        if mode is CancelMode.SELF and self._active_children(pcb):
            raise OperationDenied("self cancellation would orphan attached children")
        selected = (
            self._cancellation_postorder(pcb) if mode is CancelMode.TREE else (pcb,)
        )
        if any(item.state is ProcessState.FAILING for item in selected):
            raise OperationDenied(
                "an abnormal failure decision already won in cancellation tree"
            )
        error = ProcessError(
            code="process_cancelled", message=reason, origin=ErrorOrigin.KERNEL
        )
        predecessor: ProcessControlBlock | None = None
        for item in selected:
            if self._commit_decision(item, ProcessState.CANCELLED, error=error):
                self._start_finalizer(item, predecessor=predecessor)
            predecessor = item

    def inspect(self, pid: int) -> ProcessSnapshot:
        return self._snapshot(self._get_process(pid))

    def list_processes(self) -> tuple[ProcessSnapshot, ...]:
        return tuple(
            self._snapshot(self._processes[pid]) for pid in sorted(self._processes)
        )

    def tree(self, pid: int) -> tuple[ProcessSnapshot, ...]:
        ordered: list[ProcessSnapshot] = []
        pending = [self._get_process(pid)]
        while pending:
            pcb = pending.pop()
            ordered.append(self._snapshot(pcb))
            for child_pid in sorted(pcb.child_pids, reverse=True):
                child = self._processes.get(child_pid)
                if child is not None:
                    pending.append(child)
        return tuple(ordered)

    async def reap(self, pid: int) -> ProcessResult:
        pcb = self._get_process(pid)
        if pcb.state not in COMPLETION_STATES or pcb.result is None:
            raise InvalidKernelState(f"cannot reap active process {pid}")
        if pcb.child_pids:
            raise InvalidKernelState(
                f"cannot reap process {pid} while it owns children"
            )
        if any(
            other.waiting_for is not None and pid in other.waiting_for
            for other in self._processes.values()
        ):
            raise InvalidKernelState(f"process {pid} is referenced by an active wait")
        owner_pid = pcb.context.owner_pid
        if owner_pid is not None and owner_pid in self._processes:
            self._processes[owner_pid].child_pids.discard(pid)
        pcb.state = ProcessState.REAPED
        del self._processes[pid]
        return pcb.result

    def _require_running(self) -> None:
        if self._state is not KernelState.RUNNING:
            raise KernelNotRunning("kernel is not running")

    def _get_process(self, pid: int) -> ProcessControlBlock:
        try:
            return self._processes[pid]
        except KeyError as exc:
            raise ProcessNotFound(f"process not found: {pid}") from exc

    def _admit_many(
        self,
        specs: tuple[ProcessSpec, ...],
        *,
        principal: Principal,
        parent_pid: int | None,
        authority_ceiling: Authority | None = None,
    ) -> tuple[int, ...]:
        if len(self._processes) + len(specs) > self.max_processes:
            raise OperationDenied("process limit exceeded")
        parent = self._get_process(parent_pid) if parent_pid is not None else None
        if parent is not None and parent.state not in {
            ProcessState.READY,
            ProcessState.RUNNING,
            ProcessState.WAITING,
        }:
            raise OperationDenied(
                "parent process cannot create children in its current state"
            )
        prepared: list[
            tuple[ProcessSpec, ProcessImage, ProcessProgram, Authority, Mapping[str, Any]]
        ] = []
        for spec in specs:
            metadata = freeze_public_value(spec.metadata)
            image = self.catalog.resolve(
                image=spec.image,
                capability=spec.capability,
                provider=spec.provider,
            )
            authority = self._effective_authority(
                spec,
                image,
                parent,
                principal=principal,
                authority_ceiling=authority_ceiling,
            )
            prepared.append((spec, image, image.factory(), authority, metadata))
        loop = asyncio.get_running_loop()
        pids: list[int] = []
        for spec, image, program, authority, metadata in prepared:
            pid = self._allocate_pid()
            owner_pid = (
                parent_pid
                if parent_pid is not None and spec.ownership is OwnershipMode.ATTACHED
                else None
            )
            context = ProcessContext(
                pid=pid,
                owner_pid=owner_pid,
                spawned_by_pid=parent_pid,
                image_id=image.image_id,
                image_version=image.version,
                principal=principal,
                authority=authority,
                input=spec.input,
                metadata=metadata,
            )
            pcb = ProcessControlBlock(
                context=context,
                program=program,
                state=ProcessState.READY,
                started_at=datetime.now(UTC),
                completion=loop.create_future(),
            )
            pcb.mailbox.append(Started())
            self._processes[pid] = pcb
            if owner_pid is not None:
                self._processes[owner_pid].child_pids.add(pid)
            pids.append(pid)
        for pid in pids:
            self._schedule(self._processes[pid])
        return tuple(pids)

    def _effective_authority(
        self,
        spec: ProcessSpec,
        image: ProcessImage,
        parent: ProcessControlBlock | None,
        *,
        principal: Principal,
        authority_ceiling: Authority | None,
    ) -> Authority:
        if (
            image.execute_principals is not None
            and principal not in image.execute_principals
        ):
            result_decision = AdmissionDecision.DENY
            granted = Authority.empty()
            reason = "principal is not permitted by image execute ACL"
            approval_id = None
        else:
            caller_authority = (
                parent.context.authority if parent is not None else authority_ceiling
            )
            result = self.policy.evaluate(
                AdmissionRequest(
                    principal=principal,
                    image_reference=image.reference,
                    requester_pid=parent.pid if parent is not None else None,
                    caller_authority=caller_authority,
                    requested_authority=spec.requested_authority,
                    image_authority_ceiling=image.authority_ceiling,
                    image_authority_requirements=image.authority_requirements,
                    approval=spec.approval,
                )
            )
            result_decision = result.decision
            granted = result.granted_authority
            reason = result.reason
            approval_id = result.approval_id
        self._authority_audit.append(
            AuthorityDecisionRecord(
                occurred_at=datetime.now(UTC),
                principal=principal,
                requester_pid=parent.pid if parent is not None else None,
                image_reference=image.reference,
                requested_authority=spec.requested_authority,
                granted_authority=granted,
                decision=result_decision,
                reason=reason,
                approval_id=approval_id,
            )
        )
        if result_decision is AdmissionDecision.REQUIRE_APPROVAL:
            raise ApprovalRequired(reason)
        if result_decision is AdmissionDecision.DENY:
            raise OperationDenied(reason)
        return granted

    def _allocate_pid(self) -> int:
        pid = self._next_pid
        self._next_pid += 1
        self._reserved_pids.add(pid)
        return pid

    def _schedule(self, pcb: ProcessControlBlock) -> None:
        if (
            self._state is not KernelState.RUNNING
            or pcb.decision is not None
            or pcb.state is not ProcessState.READY
            or (pcb.runner is not None and not pcb.runner.done())
        ):
            return
        task = asyncio.create_task(self._activate(pcb))
        pcb.runner = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _activate(self, pcb: ProcessControlBlock) -> None:
        try:
            async with self._slots:
                if (
                    pcb.decision is not None
                    or pcb.state is not ProcessState.READY
                    or not pcb.mailbox
                ):
                    return
                event = pcb.mailbox.popleft()
                pcb.state = ProcessState.RUNNING
                self._running_count += 1
                self.peak_running = max(self.peak_running, self._running_count)
                try:
                    action = await pcb.program.handle(pcb.context, event)
                finally:
                    self._running_count -= 1
            if pcb.decision is None and pcb.state is ProcessState.RUNNING:
                await self._apply_action(pcb, action)
        except asyncio.CancelledError:
            if pcb.decision is None:
                await self._fail_abnormally(pcb, RuntimeError("runner cancelled"))
        except Exception as exc:  # noqa: BLE001
            await self._fail_abnormally(pcb, exc)
        finally:
            pcb.runner = None
            if pcb.state is ProcessState.READY:
                self._schedule(pcb)

    async def _apply_action(
        self, pcb: ProcessControlBlock, action: ProcessAction
    ) -> None:
        if isinstance(action, Yield):
            if action.next_event is not None:
                pcb.mailbox.append(action.next_event)
            self._yield_or_wait(pcb)
        elif isinstance(action, Send):
            try:
                self._deliver_message(
                    Message(
                        source_pid=pcb.pid,
                        target_pid=action.target_pid,
                        kind=action.kind,
                        payload=action.payload,
                        correlation_id=action.correlation_id,
                    )
                )
            except (ProcessNotFound, InvalidKernelState) as exc:
                self._reject(pcb, "send", exc)
            else:
                self._yield_or_wait(pcb)
        elif isinstance(action, Spawn):
            await self._apply_spawn(pcb, action)
        elif isinstance(action, DiscoverImages):
            pcb.mailbox.append(ImagesDiscovered(self.list_images()))
            pcb.state = ProcessState.READY
        elif isinstance(action, InvokeResource):
            await self._apply_resource(pcb, action)
        elif isinstance(action, Wait):
            self._apply_wait(pcb, action)
        elif isinstance(action, Cancel):
            await self._apply_cancel(pcb, action)
        elif isinstance(action, Detach):
            self._apply_detach(pcb, action)
        elif isinstance(action, Exit):
            self._finish_or_reject(pcb, ProcessState.EXITED, action.result, None)
        elif isinstance(action, Fail):
            self._finish_or_reject(
                pcb,
                ProcessState.FAILED,
                None,
                self._normalize_error(action.error, ErrorOrigin.PROGRAM),
            )
        else:
            await self._fail_abnormally(pcb, InvalidAction(type(action).__name__))

    async def _apply_resource(
        self, pcb: ProcessControlBlock, action: InvokeResource
    ) -> None:
        invocation_id = self._allocate_resource_invocation_id()
        binding = self.resources.get(action.binding_id)
        if binding is None:
            self._reject_resource(
                pcb, invocation_id, action, ResourceErrorCode.UNKNOWN_BINDING
            )
            return
        required_permission = binding.descriptor.operations.get(action.operation)
        if required_permission is None:
            self._reject_resource(
                pcb, invocation_id, action, ResourceErrorCode.UNSUPPORTED_OPERATION
            )
            return
        if required_permission not in pcb.context.authority.permissions:
            self._reject_resource(
                pcb,
                invocation_id,
                action,
                ResourceErrorCode.AUTHORITY_DENIED,
                required_permission,
            )
            return
        try:
            frozen_input = freeze_resource_value(action.input)
        except (TypeError, ValueError):
            self._reject_resource(
                pcb,
                invocation_id,
                action,
                ResourceErrorCode.MALFORMED_INPUT,
                required_permission,
            )
            return

        async with self._decision_lock:
            if pcb.state is not ProcessState.RUNNING:
                return
            if self._resource_in_flight >= self.max_resource_invocations:
                self._reject_resource(
                    pcb,
                    invocation_id,
                    action,
                    ResourceErrorCode.CAPACITY_EXCEEDED,
                    required_permission,
                )
                return
            invocation = ResourceInvocation(
                invocation_id=invocation_id,
                binding_id=action.binding_id,
                operation=action.operation,
                caller_pid=pcb.pid,
                principal=pcb.context.principal,
                authority=pcb.context.authority,
                input=frozen_input,
            )
            record = ResourceTaskRecord(invocation, required_permission)
            self._resource_tasks[invocation_id] = record
            self._resource_in_flight += 1
            pcb.pending_resource_invocation_id = invocation_id
            pcb.state = ProcessState.WAITING
            self._audit_resource(
                invocation,
                ResourceAuditPhase.ADMITTED,
                required_permission=required_permission,
            )
            task = asyncio.create_task(
                self._run_resource(record, binding.bridge)
            )
            record.task = task

            def settle_prestart_cancellation(completed: asyncio.Task[None]) -> None:
                self._resource_task_done(record, completed)

            task.add_done_callback(settle_prestart_cancellation)

    def _resource_task_done(
        self, record: ResourceTaskRecord, task: asyncio.Task[None]
    ) -> None:
        """Settle a task cancelled before its coroutine first executes."""

        if task.cancelled() and not record.slot_released:
            asyncio.create_task(
                self._settle_resource(
                    record, error_code=ResourceErrorCode.CANCELLED
                )
            )

    async def _run_resource(
        self, record: ResourceTaskRecord, bridge: HostResourceBridge
    ) -> None:
        try:
            value = await bridge.invoke(record.invocation)
        except asyncio.CancelledError:
            await self._settle_resource(
                record, error_code=ResourceErrorCode.CANCELLED
            )
        except ResourceBridgeError as exc:
            await self._settle_resource(record, error_code=exc.code)
        except Exception:  # noqa: BLE001
            await self._settle_resource(
                record, error_code=ResourceErrorCode.BRIDGE_FAILURE
            )
        else:
            await self._settle_resource(record, value=value)

    async def _settle_resource(
        self,
        record: ResourceTaskRecord,
        *,
        value: Any = None,
        error_code: ResourceErrorCode | None = None,
    ) -> None:
        invocation = record.invocation
        should_schedule = False
        async with self._decision_lock:
            pcb = self._processes.get(invocation.caller_pid)
            eligible = (
                not record.suppressed
                and pcb is not None
                and pcb.state is ProcessState.WAITING
                and pcb.pending_resource_invocation_id == invocation.invocation_id
            )
            self._release_resource_slot(record)
            if eligible:
                assert pcb is not None
                pcb.pending_resource_invocation_id = None
                if error_code is None:
                    pcb.mailbox.appendleft(
                        ResourceCompleted(
                            invocation.invocation_id,
                            invocation.binding_id,
                            invocation.operation,
                            value,
                        )
                    )
                    phase = ResourceAuditPhase.COMPLETED
                else:
                    pcb.mailbox.appendleft(
                        ResourceRejected(
                            invocation.invocation_id,
                            invocation.binding_id,
                            invocation.operation,
                            self._resource_error(error_code),
                        )
                    )
                    phase = ResourceAuditPhase.FAILED
                pcb.state = ProcessState.READY
                should_schedule = True
            else:
                phase = (
                    ResourceAuditPhase.LATE_COMPLETED
                    if error_code is None
                    else ResourceAuditPhase.LATE_FAILED
                )
            self._audit_resource(
                invocation,
                phase,
                required_permission=record.required_permission,
                error_code=error_code,
            )
        if should_schedule:
            assert pcb is not None
            self._schedule(pcb)

    def _reject_resource(
        self,
        pcb: ProcessControlBlock,
        invocation_id: ResourceInvocationId,
        action: InvokeResource,
        error_code: ResourceErrorCode,
        required_permission: Permission | None = None,
    ) -> None:
        pcb.mailbox.appendleft(
            ResourceRejected(
                invocation_id,
                action.binding_id,
                action.operation,
                self._resource_error(error_code),
            )
        )
        pcb.state = ProcessState.READY
        self._resource_audit.append(
            ResourceAuditEvent(
                occurred_at=datetime.now(UTC),
                invocation_id=invocation_id,
                caller_pid=pcb.pid,
                principal=pcb.context.principal,
                binding_id=action.binding_id,
                operation=action.operation,
                phase=ResourceAuditPhase.REJECTED,
                required_permission=required_permission,
                error_code=error_code,
            )
        )

    def _allocate_resource_invocation_id(self) -> ResourceInvocationId:
        invocation_id = ResourceInvocationId(self._next_resource_invocation_id)
        self._next_resource_invocation_id += 1
        return invocation_id

    def _release_resource_slot(self, record: ResourceTaskRecord) -> None:
        if record.slot_released:
            return
        record.slot_released = True
        self._resource_tasks.pop(record.invocation.invocation_id, None)
        self._resource_in_flight -= 1
        if self._resource_in_flight < 0:
            raise InvalidKernelState("resource capacity accounting underflow")

    def _audit_resource(
        self,
        invocation: ResourceInvocation,
        phase: ResourceAuditPhase,
        *,
        required_permission: Permission | None = None,
        error_code: ResourceErrorCode | None = None,
    ) -> None:
        self._resource_audit.append(
            ResourceAuditEvent(
                occurred_at=datetime.now(UTC),
                invocation_id=invocation.invocation_id,
                caller_pid=invocation.caller_pid,
                principal=invocation.principal,
                binding_id=invocation.binding_id,
                operation=invocation.operation,
                phase=phase,
                required_permission=required_permission,
                error_code=error_code,
            )
        )

    @staticmethod
    def _resource_error(code: ResourceErrorCode) -> ProcessError:
        messages = {
            ResourceErrorCode.UNKNOWN_BINDING: "resource binding is unknown",
            ResourceErrorCode.UNSUPPORTED_OPERATION: "resource operation is unsupported",
            ResourceErrorCode.AUTHORITY_DENIED: "resource authority was denied",
            ResourceErrorCode.CAPACITY_EXCEEDED: "resource capacity exceeded",
            ResourceErrorCode.MALFORMED_INPUT: "resource input is malformed",
            ResourceErrorCode.NOT_FOUND: "resource was not found",
            ResourceErrorCode.LIMIT_EXCEEDED: "resource limit exceeded",
            ResourceErrorCode.BRIDGE_FAILURE: "resource bridge failed",
            ResourceErrorCode.CANCELLED: "resource invocation was cancelled",
        }
        origin = (
            ErrorOrigin.POLICY
            if code is ResourceErrorCode.AUTHORITY_DENIED
            else ErrorOrigin.HOST
            if code
            in {
                ResourceErrorCode.MALFORMED_INPUT,
                ResourceErrorCode.NOT_FOUND,
                ResourceErrorCode.LIMIT_EXCEEDED,
                ResourceErrorCode.BRIDGE_FAILURE,
            }
            else ErrorOrigin.KERNEL
        )
        return ProcessError(code=code.value, message=messages[code], origin=origin)

    async def _apply_spawn(self, pcb: ProcessControlBlock, action: Spawn) -> None:
        if action.wait and any(
            spec.ownership is OwnershipMode.DETACHED for spec in action.specs
        ):
            self._reject(
                pcb,
                "spawn",
                OperationDenied("waiting Spawn requires attached process specs"),
            )
            return
        try:
            child_pids = self._admit_many(
                action.specs, principal=pcb.context.principal, parent_pid=pcb.pid
            )
        except (LookupError, OperationDenied, TypeError, ValueError) as exc:
            self._reject(pcb, "spawn", exc)
            return
        if action.wait:
            self._register_wait(pcb, frozenset(child_pids), action.wait_mode)
        else:
            pcb.mailbox.append(Spawned(child_pids))
            pcb.state = ProcessState.READY

    def _apply_wait(self, pcb: ProcessControlBlock, action: Wait) -> None:
        targets = frozenset(action.child_pids)
        if any(
            pid not in pcb.child_pids or pid not in self._processes for pid in targets
        ):
            self._reject(
                pcb, "wait", OperationDenied("wait targets must be direct children")
            )
        else:
            self._register_wait(pcb, targets, action.mode)

    async def _apply_cancel(self, caller: ProcessControlBlock, action: Cancel) -> None:
        try:
            target = self._get_process(action.target_pid)
            owned = self._subtree_pids(caller)
            if target.pid not in owned and Permission(
                "process.cancel", str(target.pid)
            ) not in caller.context.authority.permissions:
                raise OperationDenied(
                    "cancel target is not owned and requires process.cancel authority"
                )
            self._request_cancel(target, mode=action.mode, reason=action.reason)
        except (ProcessNotFound, InvalidKernelState, OperationDenied) as exc:
            self._reject(caller, "cancel", exc)
            return
        if caller.decision is not None:
            return
        caller.state = ProcessState.WAITING
        caller.operation_completion = target.completion

        def completed(completion: asyncio.Future[ProcessResult]) -> None:
            if caller.decision is not None or caller.operation_completion is not completion:
                return
            caller.operation_completion = None
            caller.operation_callback = None
            caller.mailbox.append(
                OperationCompleted("cancel", (target.pid,), result=completion.result())
            )
            caller.state = ProcessState.READY
            self._schedule(caller)

        caller.operation_callback = completed
        if target.completion.done():
            completed(target.completion)
        else:
            target.completion.add_done_callback(completed)

    def _apply_detach(self, caller: ProcessControlBlock, action: Detach) -> None:
        child = self._processes.get(action.child_pid)
        if (
            child is None
            or action.child_pid not in caller.child_pids
            or child.state in TERMINAL_STATES
        ):
            self._reject(
                caller, "detach", OperationDenied("target is not an active child")
            )
            return
        caller.child_pids.remove(action.child_pid)
        old = child.context
        child.context = ProcessContext(
            pid=old.pid,
            owner_pid=None,
            spawned_by_pid=old.spawned_by_pid,
            image_id=old.image_id,
            image_version=old.image_version,
            principal=old.principal,
            authority=old.authority,
            input=old.input,
            metadata=old.metadata,
        )
        caller.mailbox.append(OperationCompleted("detach", (action.child_pid,)))
        caller.state = ProcessState.READY

    def _register_wait(
        self, pcb: ProcessControlBlock, targets: frozenset[int], mode: WaitMode
    ) -> None:
        pcb.waiting_for, pcb.wait_mode = targets, mode
        self._complete_wait(pcb) if self._wait_satisfied(pcb) else setattr(
            pcb, "state", ProcessState.WAITING
        )

    def _wait_satisfied(self, pcb: ProcessControlBlock) -> bool:
        targets = pcb.waiting_for
        if targets is None or not targets:
            return True
        completed = {
            pid for pid in targets if self._processes[pid].state in COMPLETION_STATES
        }
        return (
            bool(completed) if pcb.wait_mode is WaitMode.ANY else completed == targets
        )

    def _complete_wait(self, pcb: ProcessControlBlock) -> None:
        targets = pcb.waiting_for or frozenset()
        results = tuple(
            child.result
            for pid in sorted(targets)
            if (child := self._processes[pid]).result is not None
        )
        pcb.waiting_for = pcb.wait_mode = None
        pcb.mailbox.appendleft(ChildrenCompleted(results))
        pcb.state = ProcessState.READY
        self._schedule(pcb)

    def _deliver_message(self, message: Message) -> None:
        target = self._get_process(message.target_pid)
        if target.state in TERMINAL_STATES | {
            ProcessState.CANCELLING,
            ProcessState.FAILING,
        }:
            raise InvalidKernelState(f"process {target.pid} cannot accept messages")
        target.mailbox.append(MessageReceived(message))
        if (
            target.state is ProcessState.WAITING
            and target.waiting_for is None
            and target.operation_completion is None
            and target.pending_resource_invocation_id is None
        ):
            target.state = ProcessState.READY
            self._schedule(target)

    @staticmethod
    def _yield_or_wait(pcb: ProcessControlBlock) -> None:
        pcb.state = ProcessState.READY if pcb.mailbox else ProcessState.WAITING

    def _reject(self, pcb: ProcessControlBlock, operation: str, exc: Exception) -> None:
        pcb.mailbox.append(
            OperationRejected(
                operation=operation,
                error=self._normalize_error(exc, ErrorOrigin.KERNEL),
            )
        )
        pcb.state = ProcessState.READY

    def _finish_or_reject(
        self,
        pcb: ProcessControlBlock,
        state: ProcessState,
        result: Any,
        error: ProcessError | None,
    ) -> None:
        if self._active_children(pcb):
            self._reject(
                pcb, state.value.lower(), OperationDenied("active attached children")
            )
        else:
            if self._commit_decision(pcb, state, result=result, error=error):
                self._publish_result(pcb)

    def _commit_decision(
        self,
        pcb: ProcessControlBlock,
        state: ProcessState,
        *,
        result: Any = None,
        error: ProcessError | None = None,
    ) -> bool:
        """Commit one validated, frozen winner in the event-loop thread."""

        if pcb.decision is not None or pcb.result is not None:
            return False
        frozen = freeze_public_value(result)
        if state not in COMPLETION_STATES or (
            state is ProcessState.FAILED and error is None
        ):
            raise InvalidKernelState("invalid terminal decision")
        pcb.decision = TerminalDecision(state, datetime.now(UTC), frozen, error)
        pcb.state = (
            ProcessState.CANCELLING
            if state is ProcessState.CANCELLED
            else ProcessState.FAILING
            if state is ProcessState.FAILED
            else pcb.state
        )
        if pcb.operation_completion is not None and pcb.operation_callback is not None:
            pcb.operation_completion.remove_done_callback(pcb.operation_callback)
        pcb.operation_completion = pcb.operation_callback = None
        return True

    def _start_finalizer(
        self,
        pcb: ProcessControlBlock,
        *,
        predecessor: ProcessControlBlock | None = None,
    ) -> None:
        children = tuple(
            self._processes[pid]
            for pid in sorted(pcb.child_pids, reverse=True)
            if pid in self._processes
        )
        task = asyncio.create_task(self._finalize(pcb, children, predecessor))
        pcb.finalizer_task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._observe_task)
        self._suppress_pending_resource(pcb)

    async def _await_finalization(self, pcb: ProcessControlBlock) -> ProcessResult:
        """Supervise internal waits without turning task faults into Process results."""

        if pcb.result is not None:
            return pcb.result
        task = pcb.finalizer_task
        if task is None:
            raise InvalidKernelState(f"process {pcb.pid} has no finalizer")
        observed: set[asyncio.Future[Any]] = {pcb.completion, task}
        await asyncio.wait(observed, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            if task.cancelled():
                raise InvalidKernelState(f"process {pcb.pid} finalizer cancelled")
            if (error := task.exception()) is not None:
                raise InvalidKernelState(f"process {pcb.pid} finalizer failed") from error
        if pcb.result is None:
            raise InvalidKernelState(f"process {pcb.pid} finalizer omitted completion")
        return pcb.result

    async def _finalize(
        self,
        pcb: ProcessControlBlock,
        children: tuple[ProcessControlBlock, ...],
        predecessor: ProcessControlBlock | None,
    ) -> None:
        decision = pcb.decision
        assert decision is not None
        diagnostics: dict[str, Any] = {}
        if predecessor is not None:
            await self._await_finalization(predecessor)
        for child in children:
            if decision.state is ProcessState.FAILED:
                await self._cancel_tree_after_failures(
                    child, reason=f"owner {pcb.pid} failed"
                )
            else:
                await self._await_finalization(child)
        if decision.state is ProcessState.CANCELLED:
            assert decision.error is not None
            diagnostics = await self._complete_cancellation(pcb, decision.error.message)
        self._publish_result(pcb, diagnostics=diagnostics)

    async def _fail_abnormally(
        self, pcb: ProcessControlBlock, exc: BaseException
    ) -> None:
        if pcb.decision is not None:
            return
        if self._commit_decision(
            pcb, ProcessState.FAILED, error=self._normalize_error(exc, ErrorOrigin.PROGRAM)
        ):
            self._start_finalizer(pcb)

    async def _cancel_tree_after_failures(
        self, root: ProcessControlBlock, *, reason: str
    ) -> None:
        while True:
            try:
                self._request_cancel(root, mode=CancelMode.TREE, reason=reason)
            except OperationDenied:
                failing = [
                    item
                    for item in self._cancellation_postorder(root)
                    if item.state is ProcessState.FAILING
                ]
                if not failing:
                    raise
                for item in failing:
                    await self._await_finalization(item)
            else:
                await self._await_finalization(root)
                return

    async def _complete_cancellation(
        self, pcb: ProcessControlBlock, reason: str
    ) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {}
        runner = pcb.runner
        if (
            runner is not None
            and runner is not asyncio.current_task()
            and not runner.done()
        ):
            runner.cancel()
            if not await self._wait_bounded(runner):
                diagnostics["handler_timeout"] = True
                self._retain_draining_task(runner)

        stop_task = asyncio.create_task(pcb.program.stop(reason))
        pcb.stop_task = stop_task
        self._tasks.add(stop_task)
        stop_task.add_done_callback(self._tasks.discard)
        stop_task.add_done_callback(self._observe_task)
        if not await self._wait_bounded(stop_task):
            diagnostics["stop_timeout"] = True
            stop_task.cancel()
            self._retain_draining_task(stop_task)
        elif not stop_task.cancelled() and (error := stop_task.exception()) is not None:
            diagnostics["stop_error"] = {
                "type": type(error).__name__,
                "message": str(error) or type(error).__name__,
            }
            logger.warning(
                "process cancellation cleanup failed: pid=%s", pcb.pid, exc_info=error
            )
        return diagnostics

    def _suppress_pending_resource(self, pcb: ProcessControlBlock) -> None:
        invocation_id = pcb.pending_resource_invocation_id
        if invocation_id is None:
            return
        pcb.pending_resource_invocation_id = None
        record = self._resource_tasks.get(invocation_id)
        if record is None or record.suppressed:
            return
        record.suppressed = True
        self._audit_resource(
            record.invocation,
            ResourceAuditPhase.CANCELLED,
            required_permission=record.required_permission,
            error_code=ResourceErrorCode.CANCELLED,
        )
        if record.task is not None and not record.task.done():
            record.task.cancel()

    async def _wait_bounded(self, task: asyncio.Task[Any]) -> bool:
        done, _ = await asyncio.wait({task}, timeout=self.cancellation_timeout)
        return bool(done)

    def _retain_draining_task(self, task: asyncio.Task[Any]) -> None:
        self._draining_tasks.add(task)

        def discard(completed: asyncio.Task[Any]) -> None:
            self._draining_tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(discard)

    async def _drain_finished_tasks(self) -> None:
        await asyncio.sleep(0)
        for task in tuple(self._draining_tasks):
            if task.done():
                self._draining_tasks.discard(task)
                if not task.cancelled():
                    task.exception()

    def _publish_result(
        self,
        pcb: ProcessControlBlock,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        if pcb.result is not None:
            return
        decision = pcb.decision
        assert decision is not None
        process_result = ProcessResult(
            pid=pcb.pid,
            image_id=pcb.context.image_id,
            image_version=pcb.context.image_version,
            state=decision.state,
            started_at=pcb.started_at,
            completed_at=datetime.now(UTC),
            result=decision.result,
            error=decision.error,
            diagnostics=diagnostics or {},
        )
        pcb.state, pcb.result = decision.state, process_result
        if not pcb.completion.done():
            pcb.completion.set_result(process_result)
        owner = (
            self._processes.get(pcb.context.owner_pid)
            if pcb.context.owner_pid is not None
            else None
        )
        if (
            owner is not None
            and owner.state is ProcessState.WAITING
            and owner.waiting_for is not None
            and pcb.pid in owner.waiting_for
            and self._wait_satisfied(owner)
        ):
            self._complete_wait(owner)

    def _active_children(self, pcb: ProcessControlBlock) -> set[int]:
        return {
            pid
            for pid in pcb.child_pids
            if pid in self._processes
            and self._processes[pid].state not in TERMINAL_STATES
        }

    def _subtree_pids(self, root: ProcessControlBlock) -> set[int]:
        result: set[int] = set()
        pending = [root]
        while pending:
            pcb = pending.pop()
            result.add(pcb.pid)
            pending.extend(
                self._processes[pid] for pid in pcb.child_pids if pid in self._processes
            )
        return result

    def _cancellation_postorder(
        self, root: ProcessControlBlock
    ) -> tuple[ProcessControlBlock, ...]:
        ordered: list[ProcessControlBlock] = []

        pending = [(root, False)]
        while pending:
            pcb, visited = pending.pop()
            if visited:
                ordered.append(pcb)
                continue
            pending.append((pcb, True))
            for child_pid in sorted(pcb.child_pids, reverse=True):
                child = self._processes.get(child_pid)
                if child is not None and child.state not in COMPLETION_STATES:
                    pending.append((child, False))
        return tuple(ordered)

    @staticmethod
    def _normalize_error(
        error: BaseException | ProcessError | str, origin: ErrorOrigin
    ) -> ProcessError:
        if isinstance(error, ProcessError):
            return error
        return ProcessError(
            code=type(error).__name__
            if isinstance(error, BaseException)
            else "failure",
            message=str(error) or type(error).__name__,
            origin=origin,
        )

    @staticmethod
    def _snapshot(pcb: ProcessControlBlock) -> ProcessSnapshot:
        return ProcessSnapshot(
            pid=pcb.pid,
            owner_pid=pcb.context.owner_pid,
            spawned_by_pid=pcb.context.spawned_by_pid,
            image_id=pcb.context.image_id,
            image_version=pcb.context.image_version,
            principal=pcb.context.principal,
            authority=pcb.context.authority,
            state=pcb.state,
            child_pids=tuple(sorted(pcb.child_pids)),
            waiting_for=tuple(sorted(pcb.waiting_for or ())),
            metadata=pcb.context.metadata,
            result=pcb.result,
            pending_resource_invocation_id=pcb.pending_resource_invocation_id,
        )
