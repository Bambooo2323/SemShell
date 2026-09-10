"""Tests for the intentionally small trusted Host administration facade."""

from __future__ import annotations

import inspect

import pytest

from semshell.host import HostAdmin
from semshell.kernel import (
    Exit,
    ProcessContext,
    ProcessKernel,
    ProcessState,
    Started,
    Yield,
)
from semshell.security import Authority, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec


class ExitProgram:
    async def handle(self, context: ProcessContext, event: object):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Exit(context.input)
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


class WaitingProgram:
    async def handle(self, context: ProcessContext, event: object):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield()
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


def make_admin() -> tuple[HostAdmin, ProcessKernel]:
    catalog = ProcessCatalog()
    catalog.register(ProcessImage("exit", "1", ExitProgram))
    catalog.register(ProcessImage("waiting", "1", WaitingProgram))
    kernel = ProcessKernel(catalog)
    return HostAdmin(kernel), kernel


def test_host_admin_exposes_only_the_closed_management_surface() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(HostAdmin, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "cancel",
        "inspect",
        "spawn",
        "start",
        "stop",
        "tree",
        "wait",
    }
    assert "send" not in public_methods
    assert "deliver_console_input" not in public_methods


@pytest.mark.asyncio
async def test_host_admin_delegates_root_lifecycle_without_process_identity() -> None:
    admin, kernel = make_admin()
    principal = Principal.parse("human:admin-test")
    await admin.start()
    pid = await admin.spawn(
        ProcessSpec(image="exit@1", input="done"),
        principal,
        Authority.empty(),
    )

    assert admin.inspect(pid).principal == principal
    assert [item.pid for item in admin.tree(pid)] == [pid]
    result = await admin.wait(pid)
    assert result.result == "done"
    assert result.state is ProcessState.EXITED
    await admin.stop()
    assert not kernel.is_running


@pytest.mark.asyncio
async def test_host_admin_cancel_uses_attached_tree_semantics() -> None:
    admin, _ = make_admin()
    await admin.start()
    pid = await admin.spawn(
        ProcessSpec(image="waiting@1"),
        Principal.parse("human:admin-test"),
        None,
    )

    result = await admin.cancel(pid, "test complete")

    assert result.state is ProcessState.CANCELLED
    await admin.stop()
