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
from semshell.examples import OperatorKind, run_demo


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally small version 0.1 CLI."""

    parser = argparse.ArgumentParser(prog="semshell")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the flattened Process proof")
    demo.add_argument("--operator", choices=("human", "rule", "llm"), required=True)
    commands.add_parser("control", help="run the persistent local Control CLI")
    return parser


async def _run(operator: OperatorKind) -> dict[str, Any]:
    report = await run_demo(operator)
    return {
        "operator": report.operator,
        "result": report.result,
        "tree": [
            {
                "pid": item.pid,
                "owner_pid": item.owner_pid,
                "image": f"{item.image_id}@{item.image_version}",
                "state": item.state,
                "children": item.child_pids,
            }
            for item in report.tree
        ],
        "authority_decisions": [
            {
                "principal": str(item.principal),
                "requester_pid": item.requester_pid,
                "image": item.image_reference,
                "decision": item.decision,
                "reason": item.reason,
            }
            for item in report.authority_decisions
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one architecture demonstration and emit structured JSON."""

    arguments = build_parser().parse_args(argv)
    if arguments.command == "demo":
        operator = cast(OperatorKind, arguments.operator)
        print(json.dumps(asyncio.run(_run(operator)), indent=2))
        return 0
    try:
        return asyncio.run(run_local_control(sys.stdin, sys.stdout, sys.stderr))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
