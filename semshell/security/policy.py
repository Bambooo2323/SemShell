"""Model-agnostic admission policy contract and default implementation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from semshell.security.authority import Authority
from semshell.security.principal import Principal


class AdmissionDecision(StrEnum):
    """Possible outcomes of one non-interactive admission evaluation."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True, slots=True)
class ApprovalArtifact:
    """Policy-issued evidence for one explicit escalation decision."""

    artifact_id: str
    principal: Principal
    image_reference: str
    authority: Authority
    reason: str

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.reason:
            raise ValueError("approval artifact identity and reason must not be empty")


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    """Inputs available to policy before PID allocation."""

    principal: Principal
    image_reference: str
    requester_pid: int | None
    caller_authority: Authority | None
    requested_authority: Authority
    image_authority_ceiling: Authority | None
    image_authority_requirements: Authority
    approval: ApprovalArtifact | None = None


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Explainable, non-interactive result of one policy evaluation."""

    decision: AdmissionDecision
    granted_authority: Authority
    reason: str
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("admission result reason must not be empty")
        if (
            self.decision is not AdmissionDecision.ALLOW
            and self.granted_authority.permissions
        ):
            raise ValueError("a rejected admission cannot grant authority")


class Policy(Protocol):
    """Non-interactive policy boundary used during process admission."""

    def evaluate(self, request: AdmissionRequest) -> AdmissionResult:
        """Evaluate admission without prompting a human inside the kernel."""
        ...


class DefaultPolicy:
    """Exact-match policy with optional system limits and registered approvals."""

    def __init__(
        self,
        *,
        system_authority: Authority | None = None,
        approvals: Iterable[ApprovalArtifact] = (),
        allow_partial: bool = True,
    ) -> None:
        self.system_authority = system_authority
        self.allow_partial = allow_partial
        self._approvals = {item.artifact_id: item for item in approvals}

    def evaluate(self, request: AdmissionRequest) -> AdmissionResult:
        approved = Authority.empty()
        approval_id: str | None = None
        if request.approval is not None:
            registered = self._approvals.get(request.approval.artifact_id)
            if registered != request.approval:
                return AdmissionResult(
                    AdmissionDecision.DENY,
                    Authority.empty(),
                    "approval artifact is not registered by policy",
                )
            if (
                registered.principal != request.principal
                or registered.image_reference != request.image_reference
            ):
                return AdmissionResult(
                    AdmissionDecision.DENY,
                    Authority.empty(),
                    "approval artifact does not match requester and image",
                )
            approved = registered.authority
            approval_id = registered.artifact_id

        requested = request.requested_authority
        caller_available = (
            requested
            if request.caller_authority is None
            else request.caller_authority.union(approved)
        )
        granted = requested.intersection(caller_available)
        if self.system_authority is not None:
            granted = granted.intersection(self.system_authority)
        if request.image_authority_ceiling is not None:
            granted = granted.intersection(request.image_authority_ceiling)

        if (
            request.caller_authority is not None
            and requested.difference(caller_available).permissions
            and request.approval is None
        ):
            return AdmissionResult(
                AdmissionDecision.REQUIRE_APPROVAL,
                Authority.empty(),
                "requested authority exceeds caller authority",
            )
        if not request.image_authority_requirements.is_subset_of(granted):
            return AdmissionResult(
                AdmissionDecision.DENY,
                Authority.empty(),
                "granted authority does not satisfy image requirements",
                approval_id,
            )
        if granted != requested and not self.allow_partial:
            return AdmissionResult(
                AdmissionDecision.DENY,
                Authority.empty(),
                "policy does not permit partial authority grants",
                approval_id,
            )
        return AdmissionResult(
            AdmissionDecision.ALLOW,
            granted,
            "requested authority granted"
            if granted == requested
            else "requested authority reduced by policy or image declaration",
            approval_id,
        )
