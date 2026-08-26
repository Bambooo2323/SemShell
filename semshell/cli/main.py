"""Minimal command-line entry point for the version 0.1 architecture proof."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any, cast

from semshell import __version__
from semshell.examples import OperatorKind, run_demo


def build_parser() -> argparse.ArgumentParser:
    """Build the intentionally small version 0.1 CLI."""

    parser = argparse.ArgumentParser(prog="semshell")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the flattened Process proof")
    demo.add_argument("--operator", choices=("human", "rule", "llm"), required=True)
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
    operator = cast(OperatorKind, arguments.operator)
    print(json.dumps(asyncio.run(_run(operator)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
