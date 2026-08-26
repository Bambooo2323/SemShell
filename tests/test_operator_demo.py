"""Conformance tests for the minimal replaceable-Operator proof."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from semshell.cli.main import main
from semshell.examples import build_demo_catalog, run_demo
from semshell.host import ConsoleBridge
from semshell.kernel import ProcessKernel, ProcessState
from semshell.security import Principal
from semshell.shells import OperatorTask
from semshell.software.image import ProcessSpec


@pytest.mark.parametrize("operator", ("human", "rule", "llm"))
@pytest.mark.asyncio
async def test_same_task_uses_replaceable_operator_processes(operator: str) -> None:
    report = await run_demo(operator)  # type: ignore[arg-type]

    assert report.result == ("alpha", "beta")
    assert [item.owner_pid for item in report.tree] == [None, 1, 2, 2]
    assert [item.state for item in report.tree] == [ProcessState.EXITED] * 4
    assert [item.image_id for item in report.tree[1:]] == [
        "demo.coordinator",
        "demo.echo",
        "demo.echo",
    ]
    assert all(item.reason for item in report.authority_decisions)


@pytest.mark.asyncio
async def test_console_bridge_is_bound_to_one_human_shell() -> None:
    kernel = ProcessKernel(build_demo_catalog("human"))
    await kernel.start()
    shell_pid = await kernel.spawn(
        ProcessSpec(image="demo.human-shell@1"),
        principal=Principal.parse("human:console"),
    )
    console = ConsoleBridge(
        kernel, shell_pid, principal=Principal.parse("human:console")
    )

    await console.write_input(OperatorTask("demo.coordinate", ("one", "two")))
    result = await kernel.wait(shell_pid)

    assert result.result == ("one", "two")
    assert console.target_pid == shell_pid
    await kernel.stop()


def test_kernel_has_no_operator_role_imports_or_branches() -> None:
    kernel_directory = Path(__file__).parents[1] / "semshell" / "kernel"
    forbidden_modules = {"semshell.shells", "semshell.llm"}
    forbidden_names = {"HumanShell", "RuleShell", "LLMShell"}

    for path in kernel_directory.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert imported.isdisjoint(forbidden_modules)
        assert names.isdisjoint(forbidden_names)


@pytest.mark.parametrize("operator", ("human", "rule", "llm"))
def test_demo_cli_emits_structured_result(
    operator: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(("demo", "--operator", operator)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["operator"] == operator
    assert output["result"] == ["alpha", "beta"]
    assert len(output["tree"]) == 4
