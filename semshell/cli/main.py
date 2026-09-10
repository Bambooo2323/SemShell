"""Command-line entry points for architecture demos and local Control."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any, cast

from semshell import __version__
from semshell.cli.control import run_local_control
from semshell.examples import (
    OperatorKind,
    project_demo_report,
    project_extended_report,
    run_demo,
    run_extended_demo,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally small version 0.1 CLI."""

    parser = argparse.ArgumentParser(prog="semshell")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the flattened Process proof")
    selection = demo.add_mutually_exclusive_group(required=True)
    selection.add_argument("--operator", choices=("human", "rule", "llm"))
    selection.add_argument("--scenario", choices=("extended",))
    commands.add_parser("control", help="run the persistent local Control CLI")
    return parser


async def _run(operator: OperatorKind) -> dict[str, Any]:
    report = await run_demo(operator)
    return project_demo_report(report)


async def _run_extended() -> dict[str, Any]:
    return project_extended_report(await run_extended_demo())


def main(argv: Sequence[str] | None = None) -> int:
    """Run one architecture demonstration and emit structured JSON."""

    arguments = build_parser().parse_args(argv)
    if arguments.command == "demo":
        if arguments.scenario == "extended":
            output = asyncio.run(_run_extended())
        else:
            operator = cast(OperatorKind, arguments.operator)
            output = asyncio.run(_run(operator))
        print(json.dumps(output, indent=2))
        return 0
    try:
        return asyncio.run(run_local_control(sys.stdin, sys.stdout, sys.stderr))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
