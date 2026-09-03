"""Persistent local administration adapter over ControlGateway."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TextIO

from semshell.cli.commands import (
    HELP_TEXT,
    AdapterCommand,
    CLICommandError,
    parse_command,
)
from semshell.cli.rendering import render_adapter_error, render_reply
from semshell.control import ControlRequest, RequestHandle, RequestId
from semshell.examples.control_runtime import ControlRuntime, build_control_runtime


@dataclass(slots=True)
class LocalControlCLI:
    """Run sequential typed requests against one live local Control session."""

    runtime: ControlRuntime
    source: TextIO
    output: TextIO
    prompt_output: TextIO
    _next_request: int = 1

    async def run(self) -> int:
        exit_code = 0
        try:
            while True:
                try:
                    self.prompt_output.write("semshell> ")
                    self.prompt_output.flush()
                    line = self.source.readline()
                except KeyboardInterrupt:
                    exit_code = 130
                    break
                if line == "":
                    break
                try:
                    command = parse_command(line)
                except CLICommandError as exc:
                    self._write(render_adapter_error(exc.code, exc.message))
                    continue
                if command is AdapterCommand.HELP:
                    self.prompt_output.write(f"{HELP_TEXT}\n")
                    self.prompt_output.flush()
                    continue
                if command is AdapterCommand.QUIT:
                    break
                request_id = RequestId(f"cli-{self._next_request}")
                self._next_request += 1
                handle: RequestHandle | None = None
                try:
                    submission = asyncio.create_task(
                        self.runtime.gateway.submit(
                            self.runtime.session,
                            ControlRequest(request_id, command),
                        )
                    )
                    handle = await asyncio.shield(submission)
                    reply = await handle.wait_reply()
                except (KeyboardInterrupt, asyncio.CancelledError):
                    if handle is None:
                        handle = await asyncio.shield(submission)
                    await self.runtime.gateway.interrupt(
                        self.runtime.session,
                        request_id,
                        "local control interrupted",
                    )
                    self._write(render_reply(await handle.wait_reply()))
                    exit_code = 130
                    break
                self._write(render_reply(reply))
        except Exception:  # noqa: BLE001
            self._write(
                render_adapter_error(
                    "cli.internal_error", "local control runtime failed"
                )
            )
            exit_code = 1
        finally:
            try:
                await self.runtime.gateway.close_session(self.runtime.session)
                await self.runtime.kernel.stop()
            except Exception:  # noqa: BLE001
                exit_code = 1
        return exit_code

    def _write(self, value: str) -> None:
        self.output.write(f"{value}\n")
        self.output.flush()


async def run_local_control(
    source: TextIO, output: TextIO, prompt_output: TextIO
) -> int:
    """Build, run, and close one deterministic local Control runtime."""

    try:
        runtime = await build_control_runtime()
    except Exception:  # noqa: BLE001
        output.write(
            render_adapter_error("cli.internal_error", "local control startup failed")
            + "\n"
        )
        output.flush()
        return 1
    return await LocalControlCLI(runtime, source, output, prompt_output).run()
