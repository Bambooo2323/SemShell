"""Conformance tests for the version 0.3 local Control adapter."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from io import StringIO

import pytest

from semshell.cli.commands import AdapterCommand, CLICommandError, parse_command
from semshell.cli.control import LocalControlCLI, run_local_control
from semshell.cli.rendering import encode_public_value, render_reply
from semshell.control import ControlGateway, ControlReply, ReplyStatus, RequestId
from semshell.examples.control_runtime import ControlRuntime, build_control_runtime
from semshell.kernel import (
    ProcessContext,
    ProcessKernel,
    Started,
    Yield,
)
from semshell.kernel.operations import (
    CancelProcess,
    InspectProcess,
    InspectTree,
    ListImages,
    ListProcesses,
    SpawnProcesses,
    WaitProcess,
)
from semshell.security import Authority, Permission, Principal
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec


class PassiveProgram:
    async def handle(self, context: ProcessContext, event: object):  # type: ignore[no-untyped-def]
        if isinstance(event, Started):
            return Yield()
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


class FailingStopKernel(ProcessKernel):
    async def stop(self) -> None:
        await super().stop()
        raise RuntimeError("secret shutdown detail")


@pytest.mark.parametrize(
    ("line", "expected_type"),
    (
        ("images", ListImages),
        ("ps", ListProcesses),
        ("inspect 3", InspectProcess),
        ("tree 3", InspectTree),
        ("wait 3 --timeout 1.5", WaitProcess),
        ("cancel 3 --reason 'stop now'", CancelProcess),
        ("help", AdapterCommand),
        ("quit", AdapterCommand),
    ),
)
def test_required_commands_parse_to_typed_values(
    line: str, expected_type: type[object]
) -> None:
    value = parse_command(line)
    assert isinstance(value, expected_type)
    if isinstance(value, CancelProcess):
        assert value.reason == "stop now"


def test_spawn_parses_json_resolution_and_exact_authority() -> None:
    operation = parse_command(
        "spawn --capability demo.echo --provider demo.echo@1 "
        "--input '{\"value\":\"ok\"}' --authority workspace.read=demo.workspace"
    )
    assert isinstance(operation, SpawnProcesses)
    spec = operation.specs[0]
    assert spec.capability == "demo.echo"
    assert spec.provider == "demo.echo@1"
    assert spec.input == {"value": "ok"}
    assert spec.requested_authority == Authority.of(
        (Permission("workspace.read", "demo.workspace"),)
    )


@pytest.mark.parametrize(
    ("line", "code"),
    (
        ("send 1 payload", "cli.unknown_command"),
        ("inspect 0", "cli.invalid_value"),
        ("wait 1 --timeout nan", "cli.invalid_value"),
        ("spawn --image demo.echo@1 --input nope", "cli.invalid_json"),
        ("spawn --image demo.echo@1 --input NaN", "cli.invalid_json"),
        ("spawn --image a --capability b", "cli.invalid_value"),
        ("cancel 1 --reason", "cli.invalid_syntax"),
        ("cancel 1 --tree", "cli.invalid_syntax"),
    ),
)
def test_parser_failures_are_closed(line: str, code: str) -> None:
    with pytest.raises(CLICommandError) as captured:
        parse_command(line)
    assert captured.value.code == code


def test_public_encoder_is_deterministic_and_rejects_host_values() -> None:
    assert encode_public_value({"z": 1, "a": 2}) == {"a": 2, "z": 1}
    assert encode_public_value(
        Authority.of((Permission("z"), Permission("a", "scope")))
    ) == {
        "permissions": [
            {"capability": "a", "scope": "scope"},
            {"capability": "z", "scope": None},
        ]
    }
    assert encode_public_value(datetime(2026, 1, 2, tzinfo=UTC)).endswith(
        ".000000Z"
    )
    with pytest.raises(TypeError):
        encode_public_value(object())
    with pytest.raises(TypeError):
        encode_public_value(float("nan"))

    @dataclass
    class HostCredential:
        secret: str

    with pytest.raises(TypeError):
        encode_public_value(HostCredential("must-not-be-rendered"))

    @dataclass(frozen=True, slots=True)
    class HostPermission(Permission):
        secret: str = "must-not-be-rendered"

    with pytest.raises(TypeError):
        encode_public_value(HostPermission("demo"))

    class HostSecret(StrEnum):
        VALUE = "must-not-be-rendered"

    with pytest.raises(TypeError):
        encode_public_value(HostSecret.VALUE)


def test_unencodable_reply_uses_safe_display_substitution() -> None:
    reply = ControlReply(
        RequestId("cli-1"), "InspectProcess", ReplyStatus.SUCCEEDED, object()
    )
    encoded = json.loads(render_reply(reply))
    assert encoded["status"] == "ENCODING_FAILED"
    assert encoded["error"]["code"] == "cli.encoding_failed"
    assert "object" not in render_reply(reply)


@pytest.mark.asyncio
async def test_scripted_control_session_preserves_one_live_runtime() -> None:
    source = StringIO(
        "spawn --image demo.echo@1 --input '{\"value\":\"ok\"}'\n"
        "ps\n"
        "inspect 1\n"
        "wait 1\n"
        "reap 1\n"
        "inspect 1\n"
        "send 1 forged\n"
        "images\n"
        "quit\n"
    )
    output = StringIO()
    prompts = StringIO()

    assert await run_local_control(source, output, prompts) == 0
    values = [json.loads(line) for line in output.getvalue().splitlines()]

    replies = [value for value in values if "request_id" in value]
    assert [reply["request_id"] for reply in replies] == [
        "cli-1",
        "cli-2",
        "cli-3",
        "cli-4",
        "cli-5",
        "cli-6",
    ]
    assert replies[0]["value"] == [1]
    assert replies[1]["value"][0]["pid"] == 1
    assert replies[2]["value"]["pid"] == 1
    assert replies[3]["value"]["result"] == {"value": "ok"}
    assert values[4]["adapter_error"]["code"] == "cli.unknown_command"
    assert replies[4]["value"]["pid"] == 1
    assert values[6]["adapter_error"]["code"] == "cli.unknown_command"
    assert replies[5]["operation"] == "ListImages"
    assert "semshell> " in prompts.getvalue()


@pytest.mark.asyncio
async def test_waiting_for_terminal_input_does_not_block_process_scheduling() -> None:
    runtime = await build_control_runtime()
    completed = asyncio.Event()

    class DelayedProgram(PassiveProgram):
        async def handle(self, context: ProcessContext, event: object):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.01)
            completed.set()
            return Yield()

    runtime.kernel.register_image(ProcessImage("delayed", "1", DelayedProgram))
    await runtime.kernel.spawn(
        ProcessSpec(image="delayed@1"), principal=Principal.parse("human:test")
    )

    class SlowInput(StringIO):
        def readline(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.05)
            return "quit\n"

    await LocalControlCLI(runtime, SlowInput(), StringIO(), StringIO()).run()
    assert completed.is_set()


@pytest.mark.asyncio
async def test_every_admitted_cli_command_has_one_audit_record() -> None:
    runtime = await build_control_runtime()
    output = StringIO()
    cli = LocalControlCLI(
        runtime,
        StringIO("images\nps\nquit\n"),
        output,
        StringIO(),
    )

    assert await cli.run() == 0
    request_ids = [
        json.loads(line)["request_id"] for line in output.getvalue().splitlines()
    ]
    assert request_ids == ["cli-1", "cli-2"]
    assert [str(record.request_id) for record in runtime.gateway.audit_records()] == request_ids


@pytest.mark.asyncio
async def test_keyboard_interrupt_during_input_returns_130() -> None:
    class InterruptedInput(StringIO):
        def readline(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt

    assert await run_local_control(InterruptedInput(), StringIO(), StringIO()) == 130


@pytest.mark.asyncio
async def test_startup_failure_is_safe_and_returns_one(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fail_startup():  # type: ignore[no-untyped-def]
        raise RuntimeError("secret startup detail")

    monkeypatch.setattr("semshell.cli.control.build_control_runtime", fail_startup)
    output = StringIO()

    assert await run_local_control(StringIO(), output, StringIO()) == 1
    assert "cli.internal_error" in output.getvalue()
    assert "secret" not in output.getvalue()


@pytest.mark.asyncio
async def test_authority_denial_does_not_end_cli_session() -> None:
    source = StringIO(
        "spawn --image demo.echo@1 --authority forbidden.scope\nimages\nquit\n"
    )
    output = StringIO()

    assert await run_local_control(source, output, StringIO()) == 0
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert replies[0]["status"] == "REJECTED"
    assert replies[0]["error"]["code"] == "policy.operation_denied"
    assert replies[1]["status"] == "SUCCEEDED"
    assert replies[1]["request_id"] == "cli-2"


@pytest.mark.asyncio
async def test_keyboard_interrupt_while_waiting_interrupts_observation() -> None:
    class SignalingGateway(ControlGateway):
        def __init__(self, kernel: ProcessKernel) -> None:
            super().__init__(kernel)
            self.submitted = asyncio.Event()

        async def submit(self, session, request):  # type: ignore[no-untyped-def]
            handle = await super().submit(session, request)
            self.submitted.set()
            return handle

    catalog = ProcessCatalog()
    catalog.register(ProcessImage("passive", "1", PassiveProgram))
    kernel = ProcessKernel(catalog)
    await kernel.start()
    pid = await kernel.spawn(
        ProcessSpec(image="passive@1"), principal=Principal.parse("human:bootstrap")
    )
    gateway = SignalingGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:local-control"), authority=Authority.empty()
    )
    runtime = ControlRuntime(kernel, gateway, session)
    output = StringIO()
    task = asyncio.create_task(
        LocalControlCLI(runtime, StringIO(f"wait {pid}\n"), output, StringIO()).run()
    )
    await asyncio.wait_for(gateway.submitted.wait(), timeout=1)

    task.cancel()
    assert await task == 130
    reply = json.loads(output.getvalue().splitlines()[0])
    assert reply["status"] == "INTERRUPTED"
    assert gateway.audit_records()[0].request_id == RequestId("cli-1")


@pytest.mark.asyncio
async def test_shutdown_failure_returns_one_without_leaking_exception() -> None:
    kernel = FailingStopKernel(ProcessCatalog())
    await kernel.start()
    gateway = ControlGateway(kernel)
    runtime = ControlRuntime(
        kernel,
        gateway,
        gateway.open_session(
            principal=Principal.parse("human:local-control"),
            authority=Authority.empty(),
        ),
    )
    output = StringIO()

    result = await LocalControlCLI(
        runtime, StringIO("quit\n"), output, StringIO()
    ).run()

    assert result == 1
    assert "secret" not in output.getvalue()


@pytest.mark.asyncio
async def test_all_administration_commands_route_through_gateway() -> None:
    class RecordingGateway(ControlGateway):
        def __init__(self, kernel: ProcessKernel) -> None:
            super().__init__(kernel)
            self.operations: list[str] = []

        async def submit(self, session, request):  # type: ignore[no-untyped-def]
            self.operations.append(type(request.operation).__name__)
            return await super().submit(session, request)

    base = await build_control_runtime()
    await base.gateway.close_session(base.session)
    gateway = RecordingGateway(base.kernel)
    runtime = ControlRuntime(
        base.kernel,
        gateway,
        gateway.open_session(
            principal=Principal.parse("human:local-control"),
            authority=Authority.empty(),
        ),
    )
    source = StringIO(
        "images\nps\ninspect 999\ntree 999\n"
        "spawn --image demo.echo@1 --input '\"ok\"'\n"
        "wait 1\ncancel 1\nquit\n"
    )

    assert await LocalControlCLI(runtime, source, StringIO(), StringIO()).run() == 0
    assert gateway.operations == [
        "ListImages",
        "ListProcesses",
        "InspectProcess",
        "InspectTree",
        "SpawnProcesses",
        "WaitProcess",
        "CancelProcess",
    ]


def test_cli_handlers_have_no_direct_kernel_operation_calls() -> None:
    from pathlib import Path

    source = Path("semshell/cli/control.py").read_text(encoding="utf-8")
    forbidden = (
        ".kernel.list_processes(",
        ".kernel.list_images(",
        ".kernel.spawn(",
        ".kernel.wait(",
        ".kernel.cancel(",
        ".kernel.inspect(",
        ".kernel.tree(",
    )
    assert all(call not in source for call in forbidden)
