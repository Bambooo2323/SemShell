"""Delegated authority must not become privilege escalation for the requester."""

from __future__ import annotations

import json

import pytest

from semshell.cli.main import main
from semshell.examples.delegation_demo import (
    OTHER_BINDING,
    REPORT_AUTHORITY,
    REQUEST_ID,
    DelegationUserShell,
    DemoEvidence,
    run_delegation_demo,
)
from semshell.kernel import (
    ConsoleInput,
    MessageReceived,
    ProcessContext,
    Spawned,
    Yield,
)
from semshell.kernel.events import Message
from semshell.security import Authority, Principal


@pytest.mark.asyncio
async def test_delegation_keeps_ownership_authority_and_results_separate() -> None:
    report = await run_delegation_demo()
    by_image = {item["image"]: item for item in report["tree"]}
    shell = by_image["delegation.usershell"]
    llm1 = by_image["delegation.llm1"]
    llm2 = by_image["delegation.llm2"]
    tools = [item for item in report["tree"] if item["image"] == "delegation.text-tool"]
    assert len(report["tree"]) == 5  # Denied creation did not publish another llm2.
    assert llm1["owner_pid"] == llm2["owner_pid"] == shell["pid"]
    assert len(tools) == 2
    assert all(item["owner_pid"] == llm1["pid"] for item in tools)
    assert llm1["authority"] == []
    assert llm2["authority"] == [
        {
            "capability": "workspace.read_text",
            "scope": "delegation.report",
        }
    ]
    assert shell["state"] == "WAITING"
    assert all(item["state"] == "EXITED" for item in report["tree"] if item != shell)
    assert report["result"]["delegation"]["status"] == "completed"
    assert report["result"]["delegation"]["worker_pid"] == llm2["pid"]
    assert report["model_calls"] == {"llm1": 2, "llm2": 1}
    assert report["bridge_invocations"] == {"report": 1, "other": 0}

    denials = [item for item in report["resource_audit"] if item["phase"] == "rejected"]
    assert {
        (item["caller_pid"], item["binding"], item["error"]) for item in denials
    } == {
        (llm1["pid"], "delegation.report", "resource.authority_denied"),
        (llm2["pid"], "delegation.other", "resource.authority_denied"),
    }
    spawn_denials = [
        item for item in report["authority_decisions"] if item["decision"] == "DENY"
    ]
    assert len(spawn_denials) == 1
    assert spawn_denials[0]["requester_pid"] == llm1["pid"]
    assert spawn_denials[0]["granted"] == []
    assert "caller authority" in spawn_denials[0]["reason"]

    approval = next(item for item in report["trace"] if item["event"] == "approval")
    worker_start = next(
        item for item in report["trace"] if item["event"] == "llm2_started"
    )
    expected_tools = sorted(item["pid"] for item in tools)
    assert approval["tools_running"] == worker_start["tools_running"] == expected_tools
    assert approval["requester_pid"] == llm1["pid"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "approve,binding", [(False, "delegation.report"), (True, str(OTHER_BINDING))]
)
async def test_declined_or_out_of_scope_requests_finish_without_privileged_worker(
    approve: bool,
    binding: str,
) -> None:
    report = await run_delegation_demo(approve=approve, requested_binding=binding)
    assert report["result"]["delegation"]["status"] == "denied"
    assert len(report["result"]["tools"]) == 2
    assert len(report["tree"]) == 4
    assert report["model_calls"] == {"llm1": 2, "llm2": 0}
    assert report["bridge_invocations"] == {"report": 0, "other": 0}
    assert all(item["image"] != "delegation.llm2" for item in report["tree"])


def test_delegation_cli_emits_evidence(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(("demo", "--scenario", "delegation")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scenario"] == "delegation"
    assert report["result"]["delegation"]["status"] == "completed"


@pytest.mark.asyncio
async def test_shell_approval_cannot_grant_authority_it_does_not_have() -> None:
    report = await run_delegation_demo(shell_authority=Authority.empty())
    assert report["result"]["delegation"]["status"] == "denied"
    shell = next(
        item for item in report["tree"] if item["image"] == "delegation.usershell"
    )
    assert shell["authority"] == []
    assert report["bridge_invocations"] == {"report": 0, "other": 0}
    assert report["model_calls"]["llm2"] == 0
    assert any(
        item["requester_pid"] == shell["pid"] and item["decision"] == "DENY"
        for item in report["authority_decisions"]
    )


@pytest.mark.asyncio
async def test_shell_ignores_permission_request_from_an_unrelated_sender() -> None:
    principal = Principal.parse("human:test")
    context = ProcessContext(
        pid=1,
        owner_pid=None,
        spawned_by_pid=None,
        image_id="delegation.usershell",
        image_version="1",
        principal=principal,
        authority=REPORT_AUTHORITY,
    )
    evidence = DemoEvidence()
    shell = DelegationUserShell(evidence)
    await shell.handle(context, ConsoleInput(principal, "review the report"))
    await shell.handle(context, Spawned((2,)))
    action = await shell.handle(
        context,
        MessageReceived(
            Message(
                99,
                1,
                {
                    "kind": "request_delegation",
                    "request_id": REQUEST_ID,
                    "binding_id": "delegation.report",
                    "reason": "read the report",
                },
            )
        ),
    )
    assert isinstance(action, Yield)
    assert shell.llm2_pid is None
    assert not any(item["event"] == "approval" for item in evidence.trace)
