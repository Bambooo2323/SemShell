"""Executable examples for SemShell milestones."""

from semshell.examples.architecture_demo import (
    DemoReport,
    OperatorKind,
    build_demo_catalog,
    run_demo,
)
from semshell.examples.resource_demo import (
    ResourceDemoReport,
    WorkspaceReaderProgram,
    run_resource_demo,
)

__all__ = [
    "DemoReport",
    "OperatorKind",
    "ResourceDemoReport",
    "WorkspaceReaderProgram",
    "build_demo_catalog",
    "run_demo",
    "run_resource_demo",
]
