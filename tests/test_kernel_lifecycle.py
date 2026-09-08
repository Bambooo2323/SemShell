"""Regression coverage for the phase-one and phase-two kernel lifecycle work."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from semshell.kernel import (
    Cancel,
    CancelMode,
    ConsoleInput,
    Detach,
    Exit,
    KernelState,
    MessageReceived,
    OperationCompleted,
    ProcessContext,
    ProcessKernel,
    ProcessState,
    Spawn,
    Spawned,
    Started,
    Yield,
)
from semshell.kernel.errors import InvalidKernelState, OperationDenied, ProcessNotFound
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

PRINCIPAL = Principal.parse("human:lifecycle-test")


class PassiveProgram:
    async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield()
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


def catalog_with_passive() -> ProcessCatalog:
    catalog = ProcessCatalog()
    catalog.register(ProcessImage("passive", "1", PassiveProgram))
    return catalog


async def spawn_passive(kernel: ProcessKernel, *, parent_pid: int | None = None) -> int:
    return await kernel.spawn(
        ProcessSpec(image="passive@1"), principal=PRINCIPAL, parent_pid=parent_pid
    )


@pytest.mark.asyncio
async def test_stop_survives_cancelled_waiter_reap_race_and_restarts() -> None:
    child_stop_started = asyncio.Event()
    release_child_stop = asyncio.Event()
    tail_stop_started = asyncio.Event()

    class BlockingChild(PassiveProgram):
        async def stop(self, reason: str) -> None:
            child_stop_started.set()
            await release_child_stop.wait()

    class Tail(PassiveProgram):
        async def stop(self, reason: str) -> None:
            tail_stop_started.set()

    class Owner:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-child@1"),))
            if isinstance(event, Spawned):
                return Yield()
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = catalog_with_passive()
    catalog.register(ProcessImage("blocking-child", "1", BlockingChild))
    catalog.register(ProcessImage("owner", "1", Owner))
    catalog.register(ProcessImage("tail", "1", Tail))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(ProcessSpec(image="owner@1"), principal=PRINCIPAL)

    async with asyncio.timeout(1):
        while len(kernel.tree(owner)) != 2:
            await asyncio.sleep(0)
    child = kernel.tree(owner)[1].pid
    victim = await spawn_passive(kernel)
    tail = await kernel.spawn(ProcessSpec(image="tail@1"), principal=PRINCIPAL)
    first_waiter = asyncio.create_task(kernel.stop())
    await asyncio.wait_for(child_stop_started.wait(), timeout=1)
    with pytest.raises(InvalidKernelState, match="stopping"):
        await kernel.start()
    victim_result = await kernel.cancel(victim)
    assert await kernel.reap(victim) is victim_result
    first_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_waiter
    assert kernel.state is KernelState.STOPPING

    release_child_stop.set()
    child_result = await asyncio.wait_for(kernel.wait(child), timeout=1)
    assert child_result.state is ProcessState.CANCELLED
    assert await kernel.reap(child) is child_result

    # No second stop caller drives the remaining root's cleanup.
    await asyncio.wait_for(tail_stop_started.wait(), timeout=1)
    await asyncio.wait_for(kernel.stop(), timeout=1)
    assert kernel.state is KernelState.STOPPED

    await kernel.start()
    restarted = await spawn_passive(kernel)
    assert restarted > tail
    await kernel.stop()
    assert kernel.state is KernelState.STOPPED


@pytest.mark.asyncio
async def test_concurrent_stop_callers_and_registered_wait_survive_reap() -> None:
    cleaning = asyncio.Event()
    release = asyncio.Event()
    stop_calls = 0

    class BlockingStop(PassiveProgram):
        async def stop(self, reason: str) -> None:
            nonlocal stop_calls
            stop_calls += 1
            cleaning.set()
            await release.wait()

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("blocking", "1", BlockingStop))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="blocking@1"), principal=PRINCIPAL)
    observer = asyncio.create_task(kernel.wait(pid))
    first = asyncio.create_task(kernel.stop())
    second = asyncio.create_task(kernel.stop())
    await asyncio.wait_for(cleaning.wait(), timeout=1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    assert not observer.done()
    release.set()
    await asyncio.wait_for(second, timeout=1)
    result = await kernel.reap(pid)
    assert await observer is result
    with pytest.raises(ProcessNotFound):
        await kernel.wait(pid)
    assert stop_calls == 1
    assert kernel.state is KernelState.STOPPED


@pytest.mark.asyncio
async def test_deep_tree_cancellation_and_tree_snapshot_are_iterative() -> None:
    depth = 1_100
    kernel = ProcessKernel(catalog_with_passive(), max_processes=depth + 10)
    await kernel.start()
    root = await spawn_passive(kernel)
    parent = root
    for _ in range(depth - 1):
        parent = await spawn_passive(kernel, parent_pid=parent)

    assert len(kernel.tree(root)) == depth
    result = await asyncio.wait_for(
        kernel.cancel(root, mode=CancelMode.TREE, reason="deep tree"), timeout=5
    )

    assert result.state is ProcessState.CANCELLED
    assert all(
        snapshot.state is ProcessState.CANCELLED for snapshot in kernel.tree(root)
    )
    await kernel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("abnormal", [False, True])
async def test_blocked_cleanup_does_not_hold_the_only_activation_slot(abnormal: bool) -> None:
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    unrelated_started = asyncio.Event()

    class BlockingStop(PassiveProgram):
        async def stop(self, reason: str) -> None:
            cleanup_started.set()
            await release_cleanup.wait()

    class Unrelated:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                unrelated_started.set()
                return Yield()
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    class Owner(PassiveProgram):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-stop@1"),))
            if isinstance(event, Spawned):
                if abnormal:
                    raise RuntimeError("owner failed")
                return Cancel(event.pids[0])
            if isinstance(event, OperationCompleted):
                return Exit()
            raise AssertionError(f"unexpected event: {event!r}")

    catalog = catalog_with_passive()
    catalog.register(ProcessImage("blocking-stop", "1", BlockingStop))
    catalog.register(ProcessImage("unrelated", "1", Unrelated))
    catalog.register(ProcessImage("owner", "1", Owner))
    kernel = ProcessKernel(catalog, max_running=1)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="owner@1"), principal=PRINCIPAL
    )

    await asyncio.wait_for(cleanup_started.wait(), timeout=1)
    await kernel.spawn(ProcessSpec(image="unrelated@1"), principal=PRINCIPAL)
    await asyncio.wait_for(unrelated_started.wait(), timeout=1)

    release_cleanup.set()
    result = await kernel.wait(owner, timeout=1)
    assert result.state is (ProcessState.FAILED if abnormal else ProcessState.EXITED)
    await kernel.stop()


@pytest.mark.asyncio
async def test_self_cancel_action_finishes_without_waiting_on_its_own_completion() -> None:
    class SelfCancelling:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Cancel(context.pid)
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("self-cancelling", "1", SelfCancelling))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(image="self-cancelling@1"), principal=PRINCIPAL
    )

    result = await asyncio.wait_for(kernel.wait(pid), timeout=1)

    assert result.state is ProcessState.CANCELLED
    assert kernel.inspect(pid).state is ProcessState.CANCELLED
    await kernel.stop()


@pytest.mark.asyncio
async def test_failing_process_still_rejects_later_cancel_request() -> None:
    child_cleanup_started = asyncio.Event()
    release_child_cleanup = asyncio.Event()

    class BlockingChild(PassiveProgram):
        async def stop(self, reason: str) -> None:
            child_cleanup_started.set()
            await release_child_cleanup.wait()

    class FailingOwner:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-child@1"),))
            if isinstance(event, Spawned):
                raise TypeError("owner failure")
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = catalog_with_passive()
    catalog.register(ProcessImage("blocking-child", "1", BlockingChild))
    catalog.register(ProcessImage("failing-owner", "1", FailingOwner))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    owner = await kernel.spawn(
        ProcessSpec(image="failing-owner@1"), principal=PRINCIPAL
    )
    await asyncio.wait_for(child_cleanup_started.wait(), timeout=1)

    assert kernel.inspect(owner).state is ProcessState.FAILING
    with pytest.raises(OperationDenied, match="abnormal failure decision already won"):
        await kernel.cancel(owner, mode=CancelMode.TREE)

    release_child_cleanup.set()
    assert (await asyncio.wait_for(kernel.wait(owner), timeout=1)).state is ProcessState.FAILED
    await kernel.stop()


@pytest.mark.asyncio
async def test_cancel_action_waits_for_completion_without_waking_for_ipc_or_console() -> None:
    child_cleanup_started = asyncio.Event()
    release_child_cleanup = asyncio.Event()
    handled: list[str] = []

    class BlockingChild(PassiveProgram):
        async def stop(self, reason: str) -> None:
            child_cleanup_started.set()
            await release_child_cleanup.wait()

    class CancellingOwner:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="blocking-child@1"),))
            if isinstance(event, Spawned):
                return Cancel(event.pids[0])
            if isinstance(event, MessageReceived):
                handled.append("message")
                return Yield()
            if isinstance(event, ConsoleInput):
                handled.append("console")
                return Yield()
            if isinstance(event, OperationCompleted):
                handled.append("cancel")
                return Exit(tuple(handled))
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = catalog_with_passive()
    catalog.register(ProcessImage("blocking-child", "1", BlockingChild))
    catalog.register(ProcessImage("cancelling-owner", "1", CancellingOwner))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    source = await spawn_passive(kernel)
    owner = await kernel.spawn(
        ProcessSpec(image="cancelling-owner@1"), principal=PRINCIPAL
    )
    await asyncio.wait_for(child_cleanup_started.wait(), timeout=1)

    await kernel.send(owner, "queued", source_pid=source)
    await kernel.deliver_console_input(owner, "queued", principal=PRINCIPAL)
    await asyncio.sleep(0)
    assert handled == []

    release_child_cleanup.set()
    result = await asyncio.wait_for(kernel.wait(owner), timeout=1)
    assert result.result == ("message", "console", "cancel")
    await kernel.stop()


@pytest.mark.asyncio
async def test_stop_cancels_child_detached_after_shutdown_target_snapshot() -> None:
    first_cleanup_started = asyncio.Event()
    release_first_cleanup = asyncio.Event()
    detach_started = asyncio.Event()
    release_detach = asyncio.Event()

    class BlockingFirstRoot(PassiveProgram):
        async def stop(self, reason: str) -> None:
            first_cleanup_started.set()
            await release_first_cleanup.wait()

    class DetachingRoot:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(image="passive@1"),))
            if isinstance(event, Spawned):
                detach_started.set()
                await release_detach.wait()
                return Detach(event.pids[0])
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = catalog_with_passive()
    catalog.register(ProcessImage("blocking-first", "1", BlockingFirstRoot))
    catalog.register(ProcessImage("detaching-root", "1", DetachingRoot))
    kernel = ProcessKernel(catalog, max_running=2)
    await kernel.start()
    await kernel.spawn(ProcessSpec(image="blocking-first@1"), principal=PRINCIPAL)
    root = await kernel.spawn(
        ProcessSpec(image="detaching-root@1"), principal=PRINCIPAL
    )
    await asyncio.wait_for(detach_started.wait(), timeout=1)
    child = kernel.tree(root)[1].pid

    stopping = asyncio.create_task(kernel.stop())
    await asyncio.wait_for(first_cleanup_started.wait(), timeout=1)
    release_detach.set()
    async with asyncio.timeout(1):
        while kernel.inspect(child).owner_pid is not None:
            await asyncio.sleep(0)
    release_first_cleanup.set()

    await asyncio.wait_for(stopping, timeout=1)
    assert (await kernel.wait(child)).state is ProcessState.CANCELLED


@pytest.mark.asyncio
async def test_late_action_cannot_replace_committed_cancel_decision() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class LateExit:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                return Exit("late exit")
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("late-exit", "1", LateExit))
    kernel = ProcessKernel(catalog, cancellation_timeout=0.5)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="late-exit@1"), principal=PRINCIPAL)
    await asyncio.wait_for(started.wait(), timeout=1)

    cancelling = asyncio.create_task(kernel.cancel(pid))
    async with asyncio.timeout(1):
        while kernel._processes[pid].decision is None:  # deterministic decision barrier
            await asyncio.sleep(0)
    decision = kernel._processes[pid].decision
    assert decision is not None and decision.state is ProcessState.CANCELLED
    release.set()

    result = await asyncio.wait_for(cancelling, timeout=1)
    assert result.state is ProcessState.CANCELLED
    assert result.result is None
    assert kernel._processes[pid].decision is decision
    await kernel.stop()


@pytest.mark.asyncio
async def test_unfreezable_terminal_value_becomes_structured_failure() -> None:
    class UnfreezableResult:
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Exit(object())
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            return None

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("unfreezable", "1", UnfreezableResult))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(ProcessSpec(image="unfreezable@1"), principal=PRINCIPAL)

    result = await asyncio.wait_for(kernel.wait(pid), timeout=1)

    assert result.state is ProcessState.FAILED
    assert result.error is not None
    assert result.error.code == "TypeError"
    await kernel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["exception", "cancelled", "omitted completion"])
async def test_finalizer_fault_makes_shutdown_fail_and_keeps_stopping(
    monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    async def broken_finalizer(
        pcb: Any, children: Any, predecessor: Any
    ) -> None:
        if fault == "exception":
            raise RuntimeError("injected finalizer fault")
        if fault == "cancelled":
            raise asyncio.CancelledError

    kernel = ProcessKernel(catalog_with_passive())
    await kernel.start()
    pid = await spawn_passive(kernel)
    monkeypatch.setattr(kernel, "_finalize", broken_finalizer)

    with pytest.raises(InvalidKernelState, match="finalizer"):
        await asyncio.wait_for(kernel.stop(), timeout=1)

    assert kernel.state is KernelState.STOPPING
    pcb = kernel._processes[pid]  # fault injection needs the supervised PCB record
    assert pcb.decision is not None
    assert pcb.decision.state is ProcessState.CANCELLED
    assert not pcb.completion.done()
    with pytest.raises(InvalidKernelState, match="finalizer"):
        await kernel.stop()  # The failed shared task is not silently restarted.


@pytest.mark.asyncio
async def test_authorized_child_cancels_ancestor_without_completion_notification() -> None:
    stop_calls: list[str] = []

    class Child(PassiveProgram):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                assert context.owner_pid is not None
                return Cancel(context.owner_pid, mode=CancelMode.TREE)
            raise AssertionError("a cancelled child must not receive a continuation")

        async def stop(self, reason: str) -> None:
            stop_calls.append("child")

    class Owner(PassiveProgram):
        async def handle(self, context: ProcessContext, event: Any):  # type: ignore[no-untyped-def]
            if isinstance(event, Started):
                return Spawn((ProcessSpec(
                    image="child@1", requested_authority=context.authority
                ),))
            if isinstance(event, Spawned):
                return Yield()
            raise AssertionError(f"unexpected event: {event!r}")

        async def stop(self, reason: str) -> None:
            stop_calls.append("owner")

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("owner", "1", Owner))
    catalog.register(ProcessImage("child", "1", Child))
    kernel = ProcessKernel(catalog, max_running=1)
    await kernel.start()
    # The fresh Kernel's first PID is deterministic; authority remains exact.
    owner = await kernel.spawn(ProcessSpec(
        image="owner@1", requested_authority=Authority.of((Permission("process.cancel", "1"),))
    ), principal=PRINCIPAL)
    result = await kernel.wait(owner, timeout=1)
    assert result.state is ProcessState.CANCELLED
    assert stop_calls == ["child", "owner"]
    for snapshot in kernel.tree(owner):
        pcb = kernel._processes[snapshot.pid]
        assert pcb.operation_completion is None
        assert snapshot.state is ProcessState.CANCELLED
        assert snapshot.result is not None
        assert "handler_timeout" not in snapshot.result.diagnostics
    await kernel.stop()
