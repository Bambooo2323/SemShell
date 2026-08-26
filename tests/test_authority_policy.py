"""Authority algebra and explainable spawn-policy conformance tests."""

from __future__ import annotations

from typing import Any

import pytest

from semshell.kernel import Exit, ProcessContext, ProcessKernel, Started
from semshell.kernel.errors import ApprovalRequired, OperationDenied
from semshell.security import (
    AdmissionDecision,
    AdmissionRequest,
    ApprovalArtifact,
    Authority,
    DefaultPolicy,
    Permission,
    Principal,
)
from semshell.software.catalog import ProcessCatalog
from semshell.software.image import ProcessImage, ProcessSpec

PRINCIPAL = Principal.parse("human:alice")
READ = Permission("fs.read", "/workspace")
WRITE = Permission("fs.write", "/workspace")


class ExitProgram:
    async def handle(self, context: ProcessContext, event: object) -> Any:
        if isinstance(event, Started):
            return Exit()
        raise AssertionError(f"unexpected event: {event!r}")

    async def stop(self, reason: str) -> None:
        return None


@pytest.mark.parametrize(
    ("requested", "caller", "system", "image_ceiling", "requirements", "decision", "granted"),
    (
        ((), (), None, None, (), AdmissionDecision.ALLOW, ()),
        ((READ,), (READ, WRITE), None, None, (), AdmissionDecision.ALLOW, (READ,)),
        (
            (READ, WRITE),
            (READ, WRITE),
            (READ,),
            None,
            (),
            AdmissionDecision.ALLOW,
            (READ,),
        ),
        (
            (READ, WRITE),
            (READ, WRITE),
            None,
            (READ,),
            (),
            AdmissionDecision.ALLOW,
            (READ,),
        ),
        (
            (READ,),
            (READ,),
            None,
            None,
            (WRITE,),
            AdmissionDecision.DENY,
            (),
        ),
    ),
)
def test_policy_authority_matrix(
    requested: tuple[Permission, ...],
    caller: tuple[Permission, ...],
    system: tuple[Permission, ...] | None,
    image_ceiling: tuple[Permission, ...] | None,
    requirements: tuple[Permission, ...],
    decision: AdmissionDecision,
    granted: tuple[Permission, ...],
) -> None:
    policy = DefaultPolicy(
        system_authority=None if system is None else Authority.of(system)
    )
    result = policy.evaluate(
        AdmissionRequest(
            principal=PRINCIPAL,
            image_reference="worker@1",
            requester_pid=None,
            caller_authority=Authority.of(caller),
            requested_authority=Authority.of(requested),
            image_authority_ceiling=(
                None if image_ceiling is None else Authority.of(image_ceiling)
            ),
            image_authority_requirements=Authority.of(requirements),
        )
    )

    assert result.decision is decision
    assert result.granted_authority == Authority.of(granted)
    assert result.reason


def catalog(*, execute_principals: frozenset[Principal] | None = None) -> ProcessCatalog:
    result = ProcessCatalog()
    result.register(
        ProcessImage(
            "worker",
            "1",
            ExitProgram,
            execute_principals=execute_principals,
        )
    )
    return result


@pytest.mark.asyncio
async def test_child_escalation_requires_prior_explicit_approval() -> None:
    approval = ApprovalArtifact(
        "approval-1",
        PRINCIPAL,
        "worker@1",
        Authority.of((WRITE,)),
        "operator approved workspace writes",
    )
    kernel = ProcessKernel(catalog(), policy=DefaultPolicy(approvals=(approval,)))
    await kernel.start()
    parent = await kernel.spawn(
        ProcessSpec(image="worker@1", requested_authority=Authority.of((READ,))),
        principal=PRINCIPAL,
    )

    with pytest.raises(ApprovalRequired):
        await kernel.spawn(
            ProcessSpec(image="worker@1", requested_authority=Authority.of((WRITE,))),
            principal=PRINCIPAL,
            parent_pid=parent,
        )
    child = await kernel.spawn(
        ProcessSpec(
            image="worker@1",
            requested_authority=Authority.of((WRITE,)),
            approval=approval,
        ),
        principal=PRINCIPAL,
        parent_pid=parent,
    )

    assert kernel.inspect(child).authority == Authority.of((WRITE,))
    assert [record.decision for record in kernel.authority_decisions()] == [
        AdmissionDecision.ALLOW,
        AdmissionDecision.REQUIRE_APPROVAL,
        AdmissionDecision.ALLOW,
    ]
    assert kernel.authority_decisions()[-1].approval_id == "approval-1"
    await kernel.stop()


@pytest.mark.asyncio
async def test_image_execute_acl_is_separate_and_audited() -> None:
    kernel = ProcessKernel(
        catalog(execute_principals=frozenset((Principal.parse("service:ci"),)))
    )
    await kernel.start()

    with pytest.raises(OperationDenied, match="execute ACL"):
        await kernel.spawn(ProcessSpec(image="worker@1"), principal=PRINCIPAL)

    record = kernel.authority_decisions()[-1]
    assert record.decision is AdmissionDecision.DENY
    assert record.granted_authority == Authority.empty()
    assert "execute ACL" in record.reason
    await kernel.stop()
