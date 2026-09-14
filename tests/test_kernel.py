"""Deterministic tests for the in-process kernel."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from semshell.kernel import (
    Cancel,
    ChildrenCompleted,
    ContinuationEvent,
    Exit,
    MessageReceived,
    OperationCompleted,
    OperationRejected,
    ProcessContext,
    ProcessKernel,
    ProcessState,
    Spawn,
    Spawned,
    Started,
    Wait,
    Yield,
)
from semshell.kernel.errors import InvalidKernelState, OperationDenied
from semshell.kernel.kernel import KernelState
from semshell.security import Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import CapabilitySpec, ProcessImage, ProcessSpec


class ProgramBase:
    async def stop(self, reason: str) -> None:
        return None


@pytest.mark.asyncio
async def test_batch_metadata_failure_leaves_no_process_or_consumed_pid(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    try:
        with pytest.raises(TypeError):
            await kernel.spawn_many(
                (
                    ProcessSpec(image="passive@1"),
                    ProcessSpec(image="passive@1", metadata={"bad": object()}),
                ),
                principal=principal,
            )
        assert kernel.list_processes() == ()
        assert await kernel.spawn(ProcessSpec(image="echo@1"), principal=principal) == 1
    finally:
        await kernel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("image", ["echo@1", "failing@1", "passive@1"])
async def test_terminal_parent_cannot_admit_children(
    catalog: ProcessCatalog, principal: Principal, image: str
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    try:
        parent = await kernel.spawn(ProcessSpec(image=image), principal=principal)
        if image == "passive@1":
            await kernel.cancel(parent)
        else:
            await kernel.wait(parent, timeout=1)
        with pytest.raises(OperationDenied):
            await kernel.spawn(
                ProcessSpec(image="passive@1"), principal=principal, parent_pid=parent
            )
        assert kernel.process_count == 1
    finally:
        await kernel.stop()
    assert kernel.state is KernelState.STOPPED


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_stop_waits_for_failure_cleanup(
    catalog: ProcessCatalog, principal: Principal, nested: bool
) -> None:
    cleaning = asyncio.Event()
    release = asyncio.Event()

    class BlockingCleanup(PassiveProgram):
        async def stop(self, reason: str) -> None:
            cleaning.set()
            await release.wait()

    class FailingOwner(ProgramBase):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-cleanup@1"),))
            raise RuntimeError("owner failed")

    catalog.register(ProcessImage("blocking-cleanup", "1", BlockingCleanup))
    catalog.register(ProcessImage("failing-owner", "1", FailingOwner))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    try:
        parent = (
            await kernel.spawn(ProcessSpec(image="passive@1"), principal=principal)
            if nested else None
        )
        owner = await kernel.spawn(
            ProcessSpec(image="failing-owner@1"), principal=principal, parent_pid=parent
        )
        await asyncio.wait_for(cleaning.wait(), timeout=1)
        with pytest.raises(OperationDenied):
            await kernel.spawn(
                ProcessSpec(image="passive@1"), principal=principal, parent_pid=owner
            )
        stopping = asyncio.create_task(kernel.stop())
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, timeout=1)
        assert kernel.state is KernelState.STOPPED
        assert (await kernel.wait(owner)).state is ProcessState.FAILED
        assert all(
            item.state in {ProcessState.FAILED, ProcessState.CANCELLED}
            for item in kernel.list_processes()
        )
    finally:
        release.set()
        await kernel.stop()


class EchoProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            value = context.input
            if isinstance(value, dict) and "delay" in value:
                await asyncio.sleep(float(value["delay"]))
                value = value.get("value")
            return Exit(value)
        if isinstance(event, MessageReceived):
            return Exit(event.message.payload)
        raise AssertionError(f"unexpected event: {event!r}")


class PassiveProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield()
        if isinstance(event, MessageReceived):
            return Exit(event.message.payload)
        raise AssertionError(f"unexpected event: {event!r}")


class ContinueProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield(ContinuationEvent("next"))
        if isinstance(event, ContinuationEvent):
            return Exit(event.payload)
        raise AssertionError(f"unexpected event: {event!r}")


class EmptyWaitProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Wait()
        if isinstance(event, ChildrenCompleted):
            return Exit(tuple(event.results))
        raise AssertionError(f"unexpected event: {event!r}")


class InvalidWaitProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Wait((int(context.input),))
        if isinstance(event, OperationRejected):
            return Exit(event.error.code)
        raise AssertionError(f"unexpected event: {event!r}")


class FIFOReceiverProgram(ProgramBase):
    def __init__(self) -> None:
        self.received: list[tuple[int, Any]] = []

    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield()
        if isinstance(event, MessageReceived):
            self.received.append((event.message.source_pid, event.message.payload))
            return Exit(tuple(self.received)) if len(self.received) == 2 else Yield()
        raise AssertionError(f"unexpected event: {event!r}")


class DelayedWaitOwnerProgram(ProgramBase):
    def __init__(self) -> None:
        self.spawned = asyncio.Event()
        self.release = asyncio.Event()
        self.child_pids: tuple[int, ...] = ()

    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Spawn(
                (
                    ProcessSpec(image="echo@1", input="first"),
                    ProcessSpec(image="echo@1", input="second"),
                )
            )
        if isinstance(event, Spawned):
            self.child_pids = event.pids
            self.spawned.set()
            await self.release.wait()
            return Wait(event.pids)
        if isinstance(event, ChildrenCompleted):
            return Exit(tuple(item.result for item in event.results))
        raise AssertionError(f"unexpected event: {event!r}")


class CoordinatorProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            values = tuple(context.input)
            return Spawn(
                tuple(ProcessSpec(capability="echo", input=value) for value in values)
            )
        if isinstance(event, Spawned):
            return Wait(event.pids)
        if isinstance(event, ChildrenCompleted):
            return Exit(tuple(result.result for result in event.results))
        raise AssertionError(f"unexpected event: {event!r}")


class FailingProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        raise RuntimeError("expected failure")


class TreeOwnerProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Spawn(
                (ProcessSpec(image="passive@1"), ProcessSpec(image="passive@1"))
            )
        if isinstance(event, Spawned):
            return Yield()
        raise AssertionError(f"unexpected event: {event!r}")


class SlowStopProgram(PassiveProgram):
    async def stop(self, reason: str) -> None:
        await asyncio.sleep(60)


class CancellationResistantProgram(ProgramBase):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await self.release.wait()
        return Exit("late")


class CancelChildProgram(ProgramBase):
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Spawn((ProcessSpec(image="passive@1"),))
        if isinstance(event, Spawned):
            return Cancel(event.pids[0])
        if isinstance(event, OperationCompleted):
            return Wait((event.target_pids[0],))
        if isinstance(event, ChildrenCompleted):
            return Exit(event.results[0].state.value)
        raise AssertionError(f"unexpected event: {event!r}")


class CountingStopProgram(PassiveProgram):
    def __init__(self) -> None:
        self.stop_count = 0

    async def stop(self, reason: str) -> None:
        self.stop_count += 1


class EarlyExitOwnerProgram(ProgramBase):
    def __init__(self) -> None:
        self.exit_rejected = asyncio.Event()

    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Spawn((ProcessSpec(image="passive@1"),))
        if isinstance(event, Spawned):
            return Exit("too early")
        if isinstance(event, OperationRejected):
            self.exit_rejected.set()
            return Cancel(context.pid)
        raise AssertionError(f"unexpected event: {event!r}")


@pytest.fixture
def principal() -> Principal:
    return Principal.parse("human:test")


@pytest.fixture
def catalog() -> ProcessCatalog:
    result = ProcessCatalog()
    result.register(
        ProcessImage(
            "echo",
            "1",
            EchoProgram,
            (CapabilitySpec("echo", "Return the supplied input"),),
        )
    )
    result.register(ProcessImage("passive", "1", PassiveProgram))
    result.register(ProcessImage("continue", "1", ContinueProgram))
    result.register(ProcessImage("empty-wait", "1", EmptyWaitProgram))
    result.register(ProcessImage("invalid-wait", "1", InvalidWaitProgram))
    result.register(ProcessImage("coordinator", "1", CoordinatorProgram))
    result.register(ProcessImage("failing", "1", FailingProgram))
    result.register(ProcessImage("tree-owner", "1", TreeOwnerProgram))
    result.register(ProcessImage("slow-stop", "1", SlowStopProgram))
    result.register(ProcessImage("cancel-child", "1", CancelChildProgram))
    return result


@pytest.mark.asyncio
async def test_spawn_wait_and_retain_completed_process(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(capability="echo", input="hello"), principal=principal
    )

    result = await kernel.wait(pid, timeout=1)

    assert result.state is ProcessState.EXITED
    assert result.result == "hello"
    assert kernel.inspect(pid).state is ProcessState.EXITED
    assert kernel.inspect(pid).result is result
    assert kernel.process_count == 1
    await kernel.stop()


@pytest.mark.asyncio
async def test_passive_process_wakes_for_one_message(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="passive@1"), principal=principal)
    for _ in range(50):
        if kernel.inspect(pid).state is ProcessState.WAITING:
            break
        await asyncio.sleep(0)

    await kernel.send(pid, {"ok": True}, source_pid=999)
    result = await kernel.wait(pid, timeout=1)

    assert result.result == {"ok": True}
    await kernel.stop()


@pytest.mark.asyncio
async def test_explicit_continuation_never_creates_eventless_ready_process(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="continue@1"), principal=principal)

    result = await kernel.wait(pid, timeout=1)

    assert result.result == "next"
    await kernel.stop()


@pytest.mark.asyncio
async def test_parent_spawns_and_waits_for_attached_children(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    root = await kernel.spawn(
        ProcessSpec(image="coordinator@1", input=("a", "b", "c")),
        principal=principal,
    )

    result = await kernel.wait(root, timeout=1)
    snapshots = kernel.tree(root)

    assert result.result == ("a", "b", "c")
    assert len(snapshots) == 4
    assert all(snapshot.owner_pid == root for snapshot in snapshots[1:])
    await kernel.stop()


@pytest.mark.asyncio
async def test_empty_wait_completes_once_with_no_results(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="empty-wait@1"), principal=principal)

    result = await kernel.wait(pid, timeout=1)

    assert result.result == ()
    assert kernel.inspect(pid).waiting_for == ()
    await kernel.stop()


@pytest.mark.asyncio
async def test_wait_rejects_a_process_that_is_not_a_direct_child(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    unrelated = await kernel.spawn(ProcessSpec(image="passive@1"), principal=principal)
    waiter = await kernel.spawn(
        ProcessSpec(image="invalid-wait@1", input=unrelated), principal=principal
    )

    result = await kernel.wait(waiter, timeout=1)

    assert result.result == "OperationDenied"
    await kernel.cancel(unrelated)
    await kernel.stop()


@pytest.mark.asyncio
async def test_message_mailbox_preserves_fifo_and_source_fields(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    receiver = FIFOReceiverProgram()
    catalog.register(ProcessImage("fifo-receiver", "1", lambda: receiver))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="fifo-receiver@1"), principal=principal)
    while kernel.inspect(pid).state is not ProcessState.WAITING:
        await asyncio.sleep(0)

    await kernel.send(pid, "first", source_pid=7)
    await kernel.send(pid, "second", source_pid=8)
    result = await kernel.wait(pid, timeout=1)

    assert result.result == ((7, "first"), (8, "second"))
    await kernel.stop()


@pytest.mark.asyncio
async def test_wait_collects_children_that_completed_before_registration(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    owner_program = DelayedWaitOwnerProgram()
    catalog.register(
        ProcessImage("delayed-wait-owner", "1", lambda: owner_program)
    )
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="delayed-wait-owner@1"), principal=principal
    )
    await asyncio.wait_for(owner_program.spawned.wait(), timeout=1)
    async with asyncio.timeout(1):
        while any(
            kernel.inspect(pid).state is not ProcessState.EXITED
            for pid in owner_program.child_pids
        ):
            await asyncio.sleep(0)

    owner_program.release.set()
    result = await kernel.wait(owner, timeout=1)

    assert result.result == ("first", "second")
    await kernel.stop()


@pytest.mark.asyncio
async def test_program_exception_becomes_structured_failure(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="failing@1"), principal=principal)

    result = await kernel.wait(pid, timeout=1)

    assert result.state is ProcessState.FAILED
    assert result.error is not None
    assert result.error.code == "RuntimeError"
    assert result.error.message == "expected failure"
    await kernel.stop()


@pytest.mark.asyncio
async def test_pid_is_monotonic_while_completed_records_are_retained(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    first = await kernel.spawn(ProcessSpec(capability="echo"), principal=principal)
    await kernel.wait(first, timeout=1)
    second = await kernel.spawn(ProcessSpec(capability="echo"), principal=principal)

    assert second > first
    await kernel.stop()


@pytest.mark.asyncio
async def test_global_activation_limit_is_enforced(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog, max_running=2)
    await kernel.start()
    pids = [
        await kernel.spawn(
            ProcessSpec(capability="echo", input={"value": index, "delay": 0.01}),
            principal=principal,
        )
        for index in range(8)
    ]

    results = await asyncio.gather(*(kernel.wait(pid, timeout=1) for pid in pids))

    assert [result.result for result in results] == list(range(8))
    assert kernel.peak_running == 2
    await kernel.stop()


@pytest.mark.asyncio
async def test_tree_cancellation_reaches_attached_descendants(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    root = await kernel.spawn(ProcessSpec(image="tree-owner@1"), principal=principal)
    for _ in range(100):
        snapshots = kernel.tree(root)
        if len(snapshots) == 3 and all(
            snapshot.state is ProcessState.WAITING for snapshot in snapshots
        ):
            break
        await asyncio.sleep(0)

    result = await kernel.cancel(root, reason="test tree")
    snapshots = kernel.tree(root)

    assert result.state is ProcessState.CANCELLED
    assert all(snapshot.state is ProcessState.CANCELLED for snapshot in snapshots)
    assert all(snapshot.result is not None for snapshot in snapshots)
    await kernel.stop()


@pytest.mark.asyncio
async def test_cancelled_child_satisfies_parent_wait_with_structured_result(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(ProcessSpec(image="cancel-child@1"), principal=principal)

    result = await kernel.wait(owner, timeout=1)

    assert result.state is ProcessState.EXITED
    assert result.result == ProcessState.CANCELLED.value
    await kernel.stop()


@pytest.mark.asyncio
async def test_stop_hook_is_bounded_and_timeout_is_diagnostic(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog, cancellation_timeout=0.01)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="slow-stop@1"), principal=principal)
    for _ in range(100):
        if kernel.inspect(pid).state is ProcessState.WAITING:
            break
        await asyncio.sleep(0)

    result = await asyncio.wait_for(kernel.cancel(pid), timeout=0.2)

    assert result.state is ProcessState.CANCELLED
    assert result.diagnostics["stop_timeout"] is True
    await kernel.stop()


@pytest.mark.asyncio
async def test_late_action_from_cancellation_resistant_handler_is_discarded(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    program = CancellationResistantProgram()
    catalog.register(ProcessImage("resistant", "1", lambda: program))
    kernel = ProcessKernel(catalog, cancellation_timeout=0.01)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="resistant@1"), principal=principal)
    await asyncio.wait_for(program.started.wait(), timeout=1)

    result = await asyncio.wait_for(kernel.cancel(pid), timeout=0.2)
    program.release.set()
    for _ in range(100):
        if kernel.draining_task_count == 0:
            break
        await asyncio.sleep(0)

    assert result.state is ProcessState.CANCELLED
    assert result.diagnostics["handler_timeout"] is True
    assert kernel.inspect(pid).state is ProcessState.CANCELLED
    assert kernel.draining_task_count == 0
    await kernel.stop()


@pytest.mark.asyncio
async def test_concurrent_cancel_requests_share_one_cleanup(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    program = CountingStopProgram()
    catalog.register(ProcessImage("counting-stop", "1", lambda: program))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="counting-stop@1"), principal=principal)
    for _ in range(100):
        if kernel.inspect(pid).state is ProcessState.WAITING:
            break
        await asyncio.sleep(0)

    first, second = await asyncio.gather(kernel.cancel(pid), kernel.cancel(pid))

    assert first is second
    assert first.state is ProcessState.CANCELLED
    assert program.stop_count == 1
    await kernel.stop()


@pytest.mark.asyncio
async def test_cancellation_cleanup_survives_requester_cancellation(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    stop_started = asyncio.Event()
    release_stop = asyncio.Event()

    class BlockingStopProgram(PassiveProgram):
        async def stop(self, reason: str) -> None:
            stop_started.set()
            await release_stop.wait()

    class OwnerProgram(ProgramBase):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-stop@1"),))
            if isinstance(event, Spawned):
                return Cancel(event.pids[0])
            raise AssertionError(f"unexpected event: {event!r}")

    catalog.register(ProcessImage("blocking-stop", "1", BlockingStopProgram))
    catalog.register(ProcessImage("cancelling-owner", "1", OwnerProgram))
    kernel = ProcessKernel(catalog, cancellation_timeout=0.2)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="cancelling-owner@1"), principal=principal
    )
    await asyncio.wait_for(stop_started.wait(), timeout=1)

    owner_cancel = asyncio.create_task(
        kernel.cancel(owner, reason="cancel owner")
    )
    await asyncio.sleep(0)
    release_stop.set()
    result = await asyncio.wait_for(owner_cancel, timeout=1)

    assert result.state is ProcessState.CANCELLED
    assert all(
        item.state is ProcessState.CANCELLED for item in kernel.tree(owner)
    )
    await kernel.stop()


@pytest.mark.asyncio
async def test_parent_failure_waits_for_concurrently_failing_child(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    child_started = asyncio.Event()
    release = asyncio.Event()

    class ConcurrentlyFailingChild(ProgramBase):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            child_started.set()
            await release.wait()
            raise RuntimeError("child failed")

    class ConcurrentlyFailingOwner(ProgramBase):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="concurrent-failing-child@1"),))
            if isinstance(event, Spawned):
                await release.wait()
                raise RuntimeError("owner failed")  # noqa: TRY004
            raise AssertionError(f"unexpected event: {event!r}")

    catalog.register(
        ProcessImage("concurrent-failing-child", "1", ConcurrentlyFailingChild)
    )
    catalog.register(
        ProcessImage("concurrent-failing-owner", "1", ConcurrentlyFailingOwner)
    )
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="concurrent-failing-owner@1"), principal=principal
    )
    await asyncio.wait_for(child_started.wait(), timeout=1)
    release.set()

    owner_result = await kernel.wait(owner, timeout=1)
    child_result = await kernel.wait(kernel.tree(owner)[1].pid, timeout=1)
    assert owner_result.state is ProcessState.FAILED
    assert child_result.state is ProcessState.FAILED
    await kernel.stop()


@pytest.mark.asyncio
async def test_published_result_is_recursively_immutable(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(image="echo@1", input={"value": [1]}), principal=principal
    )
    result = await kernel.wait(pid, timeout=1)

    with pytest.raises(AttributeError):
        result.result["value"].append(2)
    assert (await kernel.wait(pid)).result == {"value": (1,)}
    await kernel.stop()


@pytest.mark.asyncio
async def test_parent_exit_is_rejected_before_explicit_tree_cancel(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    program = EarlyExitOwnerProgram()
    catalog.register(ProcessImage("early-exit-owner", "1", lambda: program))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="early-exit-owner@1"), principal=principal
    )

    await asyncio.wait_for(program.exit_rejected.wait(), timeout=1)
    result = await kernel.wait(owner, timeout=1)

    assert result.state is ProcessState.CANCELLED
    assert all(
        snapshot.state is ProcessState.CANCELLED for snapshot in kernel.tree(owner)
    )
    await kernel.stop()


@pytest.mark.asyncio
async def test_terminal_process_rejects_late_message(
    catalog: ProcessCatalog, principal: Principal
) -> None:
    kernel = ProcessKernel(catalog)
    await kernel.start()
    source = await kernel.spawn(ProcessSpec(image="passive@1"), principal=principal)
    target = await kernel.spawn(
        ProcessSpec(image="echo@1", input="done"), principal=principal
    )
    await kernel.wait(target, timeout=1)

    with pytest.raises(InvalidKernelState, match="cannot accept messages"):
        await kernel.send(target, "late", source_pid=source)

    assert kernel.inspect(target).state is ProcessState.EXITED
    await kernel.cancel(source)
    await kernel.stop()
