"""Public CLI contract for the primary and extended architecture reports."""

from __future__ import annotations

import json
from typing import Any

import pytest

from semshell.cli.main import main
from semshell.examples import UnsupportedReportValue, project_public_value


def run_cli(arguments: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> Any:
    assert main(arguments) == 0
    return json.loads(capsys.readouterr().out)


def test_primary_operator_reports_have_equivalent_architecture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reports = [
        run_cli(("demo", "--operator", operator), capsys)
        for operator in ("human", "rule", "llm")
    ]

    assert [report["result"] for report in reports] == [
        ["alpha", "beta"],
        ["alpha", "beta"],
        ["alpha", "beta"],
    ]
    assert [
        [item["image"] for item in report["tree"][1:]] for report in reports
    ] == [
        ["demo.coordinator@1", "demo.echo@1", "demo.echo@1"],
    ] * 3
    assert [
        [item["owner_pid"] for item in report["tree"]] for report in reports
    ] == [[None, 1, 2, 2]] * 3


def test_extended_report_closes_identity_authority_and_lifecycle_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = run_cli(("demo", "--scenario", "extended"), capsys)

    assert report["ipc"]["source_authenticated"] is True
    assert report["ipc"]["sender_pid"] == report["ipc"]["observed_source_pid"]
    assert report["resource"]["success"]["bridge_invocations"] == 1
    assert report["resource"]["denied"]["rejected_before_invocation"] is True
    assert report["resource"]["denied"]["bridge_invocations"] == 0
    assert report["resource"]["denied"]["result"] == {
        "error": "resource.authority_denied"
    }
    assert report["resource"]["denied"]["audit_phases"] == ["rejected"]
    assert report["cancellation"]["attached_to_owner"] is True
    assert report["cancellation"]["child_owner_pid"] == report["cancellation"][
        "owner_pid"
    ]
    assert report["cancellation"]["owner_state"] == "CANCELLED"
    assert report["cancellation"]["child_state"] == "CANCELLED"
    assert report["cancellation"]["child_result_publications"] == 1
    assert report["cancellation"]["late_outcome_suppressed"] is True
    assert "late_completed" in report["cancellation"]["resource_phases"]


def test_report_projection_rejects_arbitrary_python_objects() -> None:
    with pytest.raises(UnsupportedReportValue, match="unsupported report value"):
        project_public_value(object())
