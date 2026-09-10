"""Executable examples for SemShell milestones."""

from semshell.examples.architecture_demo import (
    DemoReport,
    OperatorKind,
    build_demo_catalog,
    run_demo,
)
from semshell.examples.extended_demo import ExtendedDemoReport, run_extended_demo
from semshell.examples.reporting import (
    UnsupportedReportValue,
    project_demo_report,
    project_extended_report,
    project_public_value,
)
from semshell.examples.resource_demo import (
    ResourceDemoReport,
    WorkspaceReaderProgram,
    run_resource_demo,
)

__all__ = [
    "DemoReport",
    "ExtendedDemoReport",
    "OperatorKind",
    "ResourceDemoReport",
    "UnsupportedReportValue",
    "WorkspaceReaderProgram",
    "build_demo_catalog",
    "project_demo_report",
    "project_extended_report",
    "project_public_value",
    "run_demo",
    "run_extended_demo",
    "run_resource_demo",
]
