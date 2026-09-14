"""Small executable proof that Operator implementations are replaceable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from semshell.kernel import (
    ChildrenCompleted,
    Exit,
    ProcessAction,
    ProcessContext,
    ProcessEvent,
    ProcessKernel,
    ProcessSnapshot,
    Spawn,
    Spawned,
    Started,
    Wait,
)
from semshell.llm import ScriptedSemanticBackend
from semshell.security import AuthorityDecisionRecord, Principal
from semshell.shells import HumanShell, LLMShell, OperatorTask, RuleShell
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import CapabilitySpec, ProcessImage, ProcessSpec
from semshell.software.program import ProcessProgram

OperatorKind = Literal["human", "rule", "llm"]


class EchoProgram:
    """Return the input supplied to this deterministic worker."""

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            return Exit(context.input)
        raise RuntimeError(f"unsupported Echo event: {type(event).__name__}")

    async def stop(self, reason: str) -> None:
        return None


class CoordinatorProgram:
    """Demonstrate fan-out/fan-in entirely through ordinary Process Actions."""

    async def handle(
        self, context: ProcessContext, event: ProcessEvent
    ) -> ProcessAction:
        if isinstance(event, Started):
            if not isinstance(context.input, (list, tuple)):
                raise TypeError("coordinator input must be a list or tuple")
            return Spawn(
                tuple(
                    ProcessSpec(capability="demo.echo", input=value)
                    for value in context.input
                )
            )
        if isinstance(event, Spawned):
            return Wait(event.pids)
        if isinstance(event, ChildrenCompleted):
            return Exit(tuple(result.result for result in event.results))
        raise RuntimeError(
            f"unsupported Coordinator event: {type(event).__name__}"
        )

    async def stop(self, reason: str) -> None:
        return None


@dataclass(frozen=True, slots=True)
class DemoReport:
    """Observable result of one Operator-independent architecture run."""

    operator: OperatorKind
    result: Any
    tree: tuple[ProcessSnapshot, ...]
    authority_decisions: tuple[AuthorityDecisionRecord, ...]


def _operator_factory(operator: OperatorKind) -> Callable[[], ProcessProgram]:
    if operator == "human":
        return HumanShell
    if operator == "rule":
        return RuleShell

    def create_llm_shell() -> ProcessProgram:
        backend = ScriptedSemanticBackend(
            (
                '{"action":"spawn","specs":['
                + '{"capability":"demo.coordinate","input":["alpha","beta"]}]}'
            ,)
        )
        return LLMShell(backend, model="scripted")

    return create_llm_shell


def build_demo_catalog(operator: OperatorKind) -> ProcessCatalog:
    """Build the same guest software set with one selected Operator image."""

    catalog = ProcessCatalog()
    catalog.register(
        ProcessImage(
            "demo.echo",
            "1",
            EchoProgram,
            capabilities=(CapabilitySpec("demo.echo", "Return input"),),
        )
    )
    catalog.register(
        ProcessImage(
            "demo.coordinator",
            "1",
            CoordinatorProgram,
            capabilities=(
                CapabilitySpec("demo.coordinate", "Fan out and aggregate"),
            ),
            required_capabilities=("demo.echo",),
        )
    )
    catalog.register(
        ProcessImage(f"demo.{operator}-shell", "1", _operator_factory(operator))
    )
    return catalog


async def run_demo(operator: OperatorKind) -> DemoReport:
    """Run the same task through one selected Operator Process."""

    kernel = ProcessKernel(build_demo_catalog(operator))
    await kernel.start()
    root_pid = await kernel.spawn(
        ProcessSpec(
            image=f"demo.{operator}-shell@1",
            input=OperatorTask("demo.coordinate", ("alpha", "beta")),
        ),
        principal=Principal.parse("human:demo"),
    )
    result = await kernel.wait(root_pid)
    report = DemoReport(
        operator=operator,
        result=result.result,
        tree=kernel.tree(root_pid),
        authority_decisions=kernel.authority_decisions(),
    )
    await kernel.stop()
    return report
