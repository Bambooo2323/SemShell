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


def catalog() -> ProcessCatalog:
    result = ProcessCatalog()
    result.register(ProcessImage("passive", "1", PassiveProgram))
    result.register(ProcessImage("exit", "1", ExitProgram))
    return result


def request(request_id: str, operation: object) -> ControlRequest:
    return ControlRequest(RequestId(request_id), operation)  # type: ignore[arg-type]


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
