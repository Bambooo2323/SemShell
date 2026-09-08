"""Executable conformance tests for the in-memory ControlGateway."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from semshell.control import (
    AuditOutcome,
    ControlGateway,
    ControlRequest,
    ReplyStatus,
    RequestId,
)
from semshell.control.gateway import CONTROL_CANCEL
from semshell.kernel import (
    Exit,
    ProcessContext,
    ProcessKernel,
    ProcessState,
    Started,
    Yield,
)
from semshell.kernel.operations import (
    InspectProcess,
    ListImages,
    ListProcesses,
    SpawnProcesses,
    WaitProcess,
)
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec


class PassiveProgram:
    async def handle(self, context: ProcessContext, event: object) -> Any:
        if isinstance(event, Started):
            return Yield()
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


class ExitProgram:
    async def handle(self, context: ProcessContext, event: object) -> Any:
        if isinstance(event, Started):
            return Exit(context.input)
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


class DelayedSpawnKernel(ProcessKernel):
    def __init__(self, catalog: ProcessCatalog) -> None:
        super().__init__(catalog)
        self.spawn_started = asyncio.Event()
        self.release_spawn = asyncio.Event()

    async def spawn_many(
        self,
        specs: tuple[ProcessSpec, ...],
        *,
        principal: Principal,
        parent_pid: int | None = None,
        authority_ceiling: Authority | None = None,
    ) -> tuple[int, ...]:
        self.spawn_started.set()
        await self.release_spawn.wait()
        return await super().spawn_many(
            specs,
            principal=principal,
            parent_pid=parent_pid,
            authority_ceiling=authority_ceiling,
        )


class AuditSignallingGateway(ControlGateway):
    def __init__(self, kernel: ProcessKernel, *, max_mutations: int = 16) -> None:
        super().__init__(kernel, max_mutations=max_mutations)
        self.late_recorded = asyncio.Event()

    def _record_late(self, *args: Any, **kwargs: Any) -> None:
        super()._record_late(*args, **kwargs)
        self.late_recorded.set()


def catalog() -> ProcessCatalog:
    result = ProcessCatalog()
    result.register(ProcessImage("passive", "1", PassiveProgram))
    result.register(ProcessImage("exit", "1", ExitProgram))
    return result


def request(request_id: str, operation: object) -> ControlRequest:
    return ControlRequest(RequestId(request_id), operation)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_processes_observes_public_deterministic_snapshots() -> None:
    kernel = ProcessKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal("test", "control"), authority=Authority.empty()
    )

    empty = await gateway.submit(session, request("empty", ListProcesses()))
    assert (await empty.wait_reply()).value == ()
    pids = await kernel.spawn_many(
        (ProcessSpec(image="passive@1"), ProcessSpec(image="passive@1")),
        principal=Principal("test", "bootstrap"),
    )
    populated = await gateway.submit(session, request("full", ListProcesses()))
    snapshots = (await populated.wait_reply()).value

    assert tuple(snapshot.pid for snapshot in snapshots) == pids
    await kernel.stop()


@pytest.mark.asyncio
async def test_interrupted_wait_does_not_cancel_target() -> None:
    kernel = ProcessKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    pid = await kernel.spawn(
        ProcessSpec(image="passive@1"), principal=session.context.principal
    )
    handle = await gateway.submit(session, request("wait", WaitProcess(pid)))

    assert await gateway.interrupt(session, RequestId("wait"))
    reply = await handle.wait_reply()

    assert reply.status is ReplyStatus.INTERRUPTED
    assert kernel.inspect(pid).state is not ProcessState.CANCELLED
    await kernel.cancel(pid)
    await gateway.close_session(session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_interrupted_dispatched_spawn_is_not_rolled_back() -> None:
    kernel = DelayedSpawnKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    handle = await gateway.submit(
        session,
        request(
            "spawn",
            SpawnProcesses((ProcessSpec(image="exit@1", input="created"),)),
        ),
    )
    await asyncio.wait_for(kernel.spawn_started.wait(), timeout=1)

    assert await gateway.interrupt(session, RequestId("spawn"))
    kernel.release_spawn.set()
    for _ in range(100):
        if any(
            record.outcome is AuditOutcome.LATE_SUCCEEDED
            for record in gateway.audit_records()
        ):
            break
        await asyncio.sleep(0)

    assert (await handle.wait_reply()).status is ReplyStatus.INTERRUPTED
    assert kernel.process_count == 1
    assert [record.outcome for record in gateway.audit_records()] == [
        AuditOutcome.INTERRUPTED,
        AuditOutcome.LATE_SUCCEEDED,
    ]
    assert gateway.audit_records()[1].details["created_pids"] == (1,)
    assert (
        gateway.audit_records()[1].details["policy_reason"]
        == "spawn admission policy accepted"
    )
    await gateway.close_session(session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_reply_during_session_close_has_only_one_terminal_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = DelayedSpawnKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    handle = await gateway.submit(
        session, request("close-success", SpawnProcesses((ProcessSpec(image="exit@1"),)))
    )
    await asyncio.wait_for(kernel.spawn_started.wait(), timeout=1)
    close_started = asyncio.Event()
    release_close = asyncio.Event()
    interrupt = handle.interrupt

    async def delayed_interrupt(reason: str) -> bool:
        close_started.set()
        await release_close.wait()
        return await interrupt(reason)

    monkeypatch.setattr(handle, "interrupt", delayed_interrupt)
    closing = asyncio.create_task(gateway.close_session(session))
    await asyncio.wait_for(close_started.wait(), timeout=1)
    kernel.release_spawn.set()
    assert (await asyncio.wait_for(handle.wait_reply(), timeout=1)).status is ReplyStatus.SUCCEEDED
    release_close.set()
    await asyncio.wait_for(closing, timeout=1)
    assert [record.outcome for record in gateway.audit_records()] == [AuditOutcome.SUCCEEDED]
    await kernel.stop()


@pytest.mark.asyncio
async def test_close_of_inflight_mutation_commits_one_reply_and_one_late_audit() -> None:
    kernel = DelayedSpawnKernel(catalog())
    await kernel.start()
    gateway = AuditSignallingGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    handle = await gateway.submit(
        session,
        request(
            "close-race",
            SpawnProcesses((ProcessSpec(image="exit@1", input="created"),)),
        ),
    )
    await asyncio.wait_for(kernel.spawn_started.wait(), timeout=1)

    await gateway.close_session(session)
    assert (await handle.wait_reply()).status is ReplyStatus.INTERRUPTED
    assert [record.outcome for record in gateway.audit_records()] == [
        AuditOutcome.INTERRUPTED
    ]

    kernel.release_spawn.set()
    await asyncio.wait_for(gateway.late_recorded.wait(), timeout=1)

    assert kernel.process_count == 1
    assert [record.outcome for record in gateway.audit_records()] == [
        AuditOutcome.INTERRUPTED,
        AuditOutcome.LATE_SUCCEEDED,
    ]
    await kernel.stop()


@pytest.mark.asyncio
async def test_observation_does_not_wait_for_mutation_capacity() -> None:
    kernel = DelayedSpawnKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel, max_mutations=1)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    spawning = await gateway.submit(
        session,
        request(
            "spawn",
            SpawnProcesses((ProcessSpec(image="exit@1", input="created"),)),
        ),
    )
    await asyncio.wait_for(kernel.spawn_started.wait(), timeout=1)

    observing = await gateway.submit(
        session, request("observe", ListProcesses())
    )
    observation = await asyncio.wait_for(observing.wait_reply(), timeout=1)

    assert observation.status is ReplyStatus.SUCCEEDED
    kernel.release_spawn.set()
    assert (await spawning.wait_reply()).status is ReplyStatus.SUCCEEDED
    await gateway.close_session(session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_gateway_normalizes_kernel_error_without_transport_errno() -> None:
    kernel = ProcessKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )

    handle = await gateway.submit(session, request("missing", InspectProcess(pid=999)))
    reply = await handle.wait_reply()

    assert reply.status is ReplyStatus.REJECTED
    assert reply.error is not None
    assert reply.error.code == "kernel.process_not_found"
    assert "errno" not in reply.error.details
    await gateway.close_session(session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_spawn_authority_cannot_exceed_session_ceiling() -> None:
    kernel = ProcessKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"), authority=Authority.empty()
    )
    requested = Authority.of((Permission("fs.write", "/workspace"),))
    handle = await gateway.submit(
        session,
        request(
            "spawn-denied",
            SpawnProcesses(
                (ProcessSpec(image="exit@1", requested_authority=requested),)
            ),
        ),
    )

    reply = await handle.wait_reply()

    assert reply.status is ReplyStatus.REJECTED
    assert reply.error is not None
    assert reply.error.code == "policy.approval_required"
    assert reply.error.retryable is True
    assert kernel.process_count == 0
    await gateway.close_session(session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_control_cancel_requires_explicit_administration_authority() -> None:
    from semshell.kernel.operations import CancelProcess

    kernel = ProcessKernel(catalog())
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(image="passive@1"), principal=Principal.parse("human:owner")
    )
    gateway = ControlGateway(kernel)
    denied_session = gateway.open_session(
        principal=Principal.parse("human:other"), authority=Authority.empty()
    )
    denied = await gateway.submit(
        denied_session, request("denied", CancelProcess(pid))
    )
    denied_reply = await denied.wait_reply()

    assert denied_reply.status is ReplyStatus.REJECTED
    assert denied_reply.error is not None
    assert denied_reply.error.code == "policy.operation_denied"
    assert kernel.inspect(pid).state is not ProcessState.CANCELLED

    admin_session = gateway.open_session(
        principal=Principal.parse("human:admin"),
        authority=Authority.of((CONTROL_CANCEL,)),
    )
    allowed = await gateway.submit(
        admin_session, request("allowed", CancelProcess(pid))
    )
    assert (await allowed.wait_reply()).status is ReplyStatus.SUCCEEDED
    assert kernel.inspect(pid).state is ProcessState.CANCELLED
    allowed_audit = gateway.audit_records()[-1]
    assert allowed_audit.details["target_pid"] == pid
    assert (
        allowed_audit.details["policy_reason"]
        == "control administration authority accepted"
    )
    await gateway.close_session(denied_session)
    await gateway.close_session(admin_session)
    await kernel.stop()


@pytest.mark.asyncio
async def test_capacity_rejection_and_session_close_are_audited() -> None:
    kernel = ProcessKernel(catalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:test"),
        authority=Authority.empty(),
        max_in_flight=1,
    )
    pid = await kernel.spawn(
        ProcessSpec(image="passive@1"), principal=session.context.principal
    )
    waiting = await gateway.submit(session, request("wait", WaitProcess(pid)))
    busy = await gateway.submit(session, request("busy", ListImages()))

    assert (await busy.wait_reply()).status is ReplyStatus.REJECTED
    await gateway.close_session(session)

    assert (await waiting.wait_reply()).status is ReplyStatus.INTERRUPTED
    assert [record.outcome for record in gateway.audit_records()] == [
        AuditOutcome.REJECTED,
        AuditOutcome.INTERRUPTED,
    ]
    await kernel.cancel(pid)
    await kernel.stop()
