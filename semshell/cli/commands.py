"""Strict local CLI parsing into transport-neutral Control operations."""

from __future__ import annotations

import json
import math
import shlex
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Never

from semshell.kernel.operations import (
    CancelProcess,
    ExternalControlOperation,
    InspectProcess,
    InspectTree,
    ListImages,
    ListProcesses,
    SpawnProcesses,
    WaitProcess,
)
from semshell.security import Authority, Permission
from semshell.software.image import ProcessSpec


class AdapterCommand(StrEnum):
    """Commands handled by the local adapter without Control admission."""

    HELP = "help"
    QUIT = "quit"


@dataclass(frozen=True, slots=True)
class CLICommandError(ValueError):
    """Closed parser failure safe for direct adapter output."""

    code: str
    message: str


ParsedCommand = ExternalControlOperation | AdapterCommand

_MESSAGES = {
    "cli.unknown_command": "command is not recognized",
    "cli.invalid_syntax": "command syntax is invalid",
    "cli.invalid_json": "input is not valid JSON",
    "cli.invalid_value": "command value is invalid",
}


def parse_command(line: str) -> ParsedCommand:
    """Parse one line without allocating a Control RequestId."""

    try:
        words = shlex.split(line, posix=True)
    except ValueError:
        _fail("cli.invalid_syntax")
    if not words:
        _fail("cli.invalid_syntax")
    name, *args = words
    if name == "help" and not args:
        return AdapterCommand.HELP
    if name in {"quit", "exit"} and not args:
        return AdapterCommand.QUIT
    if name == "images" and not args:
        return ListImages()
    if name == "ps" and not args:
        return ListProcesses()
    if name in {"inspect", "tree"}:
        if len(args) != 1:
            _fail("cli.invalid_syntax")
        pid = _positive_int(args[0])
        if name == "inspect":
            return InspectProcess(pid)
        return InspectTree(pid)
    if name == "wait":
        return _parse_wait(args)
    if name == "cancel":
        return _parse_cancel(args)
    if name == "spawn":
        return _parse_spawn(args)
    if name == "send":
        _fail("cli.unknown_command")
    _fail("cli.unknown_command")


def _parse_wait(args: list[str]) -> WaitProcess:
    if len(args) not in {1, 3}:
        _fail("cli.invalid_syntax")
    pid = _positive_int(args[0])
    timeout = None
    if len(args) == 3:
        if args[1] != "--timeout":
            _fail("cli.invalid_syntax")
        timeout = _nonnegative_finite_float(args[2])
    return WaitProcess(pid, timeout)


def _parse_cancel(args: list[str]) -> CancelProcess:
    if not args:
        _fail("cli.invalid_syntax")
    pid = _positive_int(args[0])
    reason = "cancelled from local control"
    index = 1
    seen: set[str] = set()
    while index < len(args):
        option = args[index]
        if option == "--reason" and option not in seen and index + 1 < len(args):
            reason = args[index + 1]
            if not reason:
                _fail("cli.invalid_value")
            index += 2
        else:
            _fail("cli.invalid_syntax")
        seen.add(option)
    return CancelProcess(pid, reason)


def _parse_spawn(args: list[str]) -> SpawnProcesses:
    image: str | None = None
    capability: str | None = None
    provider: str | None = None
    input_value: Any = None
    permissions: list[Permission] = []
    index = 0
    singleton_options: set[str] = set()
    while index < len(args):
        option = args[index]
        if option not in {"--image", "--capability", "--provider", "--input", "--authority"}:
            _fail("cli.invalid_syntax")
        if index + 1 >= len(args):
            _fail("cli.invalid_syntax")
        raw = args[index + 1]
        if not raw:
            _fail("cli.invalid_value")
        if option != "--authority":
            if option in singleton_options:
                _fail("cli.invalid_syntax")
            singleton_options.add(option)
        if option == "--image":
            image = raw
        elif option == "--capability":
            capability = raw
        elif option == "--provider":
            provider = raw
        elif option == "--input":
            try:
                input_value = json.loads(
                    raw,
                    parse_constant=lambda value: _reject_json_constant(value),
                )
            except (json.JSONDecodeError, ValueError):
                _fail("cli.invalid_json")
        else:
            permissions.append(_permission(raw))
        index += 2
    if (image is None) == (capability is None):
        _fail("cli.invalid_value")
    if provider is not None and capability is None:
        _fail("cli.invalid_value")
    return SpawnProcesses(
        (
            ProcessSpec(
                image=image,
                capability=capability,
                provider=provider,
                input=input_value,
                requested_authority=Authority.of(permissions),
            ),
        )
    )


def _permission(raw: str) -> Permission:
    capability, separator, scope = raw.partition("=")
    if not capability or (separator and not scope):
        _fail("cli.invalid_value")
    return Permission(capability, scope if separator else None)


def _reject_json_constant(value: str) -> Never:
    raise ValueError("non-finite JSON number")


def _positive_int(raw: str) -> int:
    try:
        value = int(raw, 10)
    except ValueError:
        _fail("cli.invalid_value")
    if value <= 0:
        _fail("cli.invalid_value")
    return value


def _nonnegative_finite_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        _fail("cli.invalid_value")
    if value < 0 or not math.isfinite(value):
        _fail("cli.invalid_value")
    return value


def _fail(code: str) -> Never:
    raise CLICommandError(code, _MESSAGES[code])


HELP_TEXT = """commands: images, ps, inspect PID, tree PID, spawn, wait PID,
cancel PID, help, quit
external send is unavailable; Process IPC requires a running Process"""
