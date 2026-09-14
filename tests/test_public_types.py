"""Smoke tests for the first stable public value objects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from semshell import CapabilitySpec, ProcessImage, ProcessKernel, ProcessSpec
from semshell.kernel import (
    KernelState,
    ProcessState,
    Send,
    Spawn,
    Wait,
)
from semshell.kernel.events import Message
from semshell.kernel.operations import SendMessage, SpawnProcesses
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

    spec = ProcessSpec(capability="echo")
    assert spec.capability == "echo"
    assert tuple(field.name for field in fields(spec)) == (
        "image",
        "capability",
        "input",
        "requested_authority",
        "metadata",
        "provider",
    )


def test_process_state_has_no_reaped_lifecycle() -> None:
    assert "REAPED" not in ProcessState.__members__


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
    action = Wait()

    assert action.child_pids == ()


def test_process_actions_are_distinct_from_control_operation_payloads() -> None:
    send = Send(target_pid=1, payload="hello")
    spawn = Spawn((ProcessSpec(capability="echo"),))

    assert not isinstance(send, SendMessage)
    assert not isinstance(spawn, SpawnProcesses)
    assert type(send).__module__ == "semshell.kernel.actions"
    assert type(spawn).__module__ == "semshell.kernel.actions"


def test_reduced_wait_spawn_and_message_fields_are_closed() -> None:
    assert [item.name for item in fields(Spawn)] == ["specs"]
    assert [item.name for item in fields(Wait)] == ["child_pids"]
    assert [item.name for item in fields(Send)] == ["target_pid", "payload"]
    assert [item.name for item in fields(Message)] == [
        "source_pid",
        "target_pid",
        "payload",
    ]


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
