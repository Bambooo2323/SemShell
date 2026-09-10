"""Fail-closed report projection for the public architecture demos."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from semshell.examples.architecture_demo import DemoReport
from semshell.examples.extended_demo import ExtendedDemoReport
from semshell.security import Authority, Permission


class UnsupportedReportValue(TypeError):
    """Raised when a demo result cannot be represented intentionally."""


def _project_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_project_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise UnsupportedReportValue("report mapping keys must be strings")
        return {key: _project_value(item) for key, item in value.items()}
    raise UnsupportedReportValue(
        f"unsupported report value: {type(value).__name__}"
    )


def project_permission(permission: Permission) -> dict[str, str | None]:
    return {"capability": permission.capability, "scope": permission.scope}


def project_authority(authority: Authority) -> list[dict[str, str | None]]:
    return [
        project_permission(permission)
        for permission in sorted(authority.permissions)
    ]


def project_demo_report(report: DemoReport) -> dict[str, Any]:
    """Project only intentional, stable fields from the primary demo."""

    return {
        "operator": report.operator,
        "result": _project_value(report.result),
        "tree": [
            {
                "pid": item.pid,
                "owner_pid": item.owner_pid,
                "image": f"{item.image_id}@{item.image_version}",
                "state": item.state.value,
                "children": list(item.child_pids),
                "granted_authority": project_authority(item.authority),
            }
            for item in report.tree
        ],
        "authority_decisions": [
            {
                "principal": str(item.principal),
                "requester_pid": item.requester_pid,
                "image": item.image_reference,
                "decision": item.decision.value,
                "reason": item.reason,
                "requested_authority": project_authority(
                    item.requested_authority
                ),
                "granted_authority": project_authority(item.granted_authority),
            }
            for item in report.authority_decisions
        ],
    }


def project_extended_report(report: ExtendedDemoReport) -> dict[str, Any]:
    """Project the closed extended-evidence schema to JSON-compatible values."""

    return {
        "scenario": "extended",
        "ipc": {
            "sender_pid": report.ipc.sender_pid,
            "observed_source_pid": report.ipc.observed_source_pid,
            "receiver_pid": report.ipc.receiver_pid,
            "payload": _project_value(report.ipc.payload),
            "source_authenticated": (
                report.ipc.sender_pid == report.ipc.observed_source_pid
            ),
        },
        "resource": {
            "required_permission": project_permission(
                report.resource.required_permission
            ),
            "success": {
                "result": _project_value(report.resource.success_result),
                "bridge_invocations": report.resource.success_invocations,
                "granted_authority": [
                    project_permission(report.resource.required_permission)
                ],
                "audit_phases": [
                    phase.value for phase in report.resource.success_phases
                ],
            },
            "denied": {
                "result": _project_value(report.resource.denied_result),
                "bridge_invocations": report.resource.denied_invocations,
                "granted_authority": [],
                "audit_phases": [
                    phase.value for phase in report.resource.denied_phases
                ],
                "rejected_before_invocation": (
                    report.resource.denied_invocations == 0
                ),
            },
        },
        "cancellation": {
            "owner_pid": report.cancellation.owner_pid,
            "child_pid": report.cancellation.child_pid,
            "child_owner_pid": report.cancellation.child_owner_pid,
            "attached_to_owner": (
                report.cancellation.child_owner_pid
                == report.cancellation.owner_pid
            ),
            "owner_state": report.cancellation.owner_state.value,
            "child_state": report.cancellation.child_state.value,
            "child_result_publications": (
                report.cancellation.child_result_publications
            ),
            "late_outcome_suppressed": (
                report.cancellation.late_outcome_suppressed
            ),
            "resource_phases": [
                phase.value for phase in report.cancellation.resource_phases
            ],
        },
    }


def project_public_value(value: Any) -> Any:
    """Validate and copy one explicitly supported report payload value."""

    return _project_value(value)
