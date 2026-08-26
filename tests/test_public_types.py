"""Smoke tests for the first stable public value objects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from semshell import CapabilitySpec, ProcessImage, ProcessKernel, ProcessSpec
from semshell.kernel import (
    KernelState,
    OwnershipMode,
    ProcessState,
    Send,
    SendMessage,
    Spawn,
    SpawnProcesses,
    Wait,
    WaitMode,
)
from semshell.security import Authority, Permission, Principal


class StubProgram:
    async def handle(self, context, event):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def stop(self, reason: str) -> None:
        return None


def test_principal_round_trip() -> None:
    principal = Principal.parse("human:alice")

    assert principal.namespace == "human"
    assert principal.subject == "alice"
    assert str(principal) == "human:alice"


def test_authority_can_only_be_reduced_by_intersection() -> None:
    read = Permission("fs.read", "/workspace")
    write = Permission("fs.write", "/workspace")
    parent = Authority.of([read, write])

    assert parent.reduced_to(Authority.of([read])) == Authority.of([read])
    assert Authority.of([read]).is_subset_of(parent)


def test_process_spec_requires_one_resolution_strategy() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ProcessSpec()
    with pytest.raises(ValueError, match="exactly one"):
        ProcessSpec(image="echo@1", capability="echo")

    spec = ProcessSpec(capability="echo", ownership=OwnershipMode.DETACHED)
    assert spec.capability == "echo"


def test_process_image_is_versioned_and_immutable() -> None:
    image = ProcessImage(
        image_id="echo",
        version="1",
        factory=StubProgram,
        capabilities=(CapabilitySpec(name="echo", description="Echo input"),),
    )

    assert image.reference == "echo@1"
    with pytest.raises(FrozenInstanceError):
        image.version = "2"  # type: ignore[misc]


def test_wait_accepts_an_empty_target_set() -> None:
    action = Wait(mode=WaitMode.ALL)

    assert action.child_pids == ()


def test_process_actions_reuse_kernel_operation_payloads() -> None:
    send = Send(target_pid=1, payload="hello")
    spawn = Spawn((ProcessSpec(capability="echo"),))

    assert isinstance(send, SendMessage)
    assert isinstance(spawn, SpawnProcesses)


def test_process_state_contains_failure_cleanup_state() -> None:
    assert ProcessState.FAILING.value == "FAILING"


@pytest.mark.asyncio
async def test_empty_kernel_start_and_stop_are_idempotent() -> None:
    kernel = ProcessKernel()

    assert kernel.state is KernelState.STOPPED
    await kernel.start()
    await kernel.start()
    assert kernel.is_running
    await kernel.stop()
    await kernel.stop()
    assert kernel.state is KernelState.STOPPED
