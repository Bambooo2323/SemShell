"""Model-agnostic admission policy contract and default implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from semshell.security.authority import Authority
from semshell.security.principal import Principal


class AdmissionDecision(StrEnum):
    """Possible outcomes of one non-interactive admission evaluation."""

    ALLOW = "ALLOW"
    DENY = "DENY"


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


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Explainable, non-interactive result of one policy evaluation."""

    decision: AdmissionDecision
    granted_authority: Authority
    reason: str

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
    """Exact-match policy bounded by caller, system, and image authority."""

    def __init__(
        self,
        *,
        system_authority: Authority | None = None,
    ) -> None:
        self.system_authority = system_authority

    def evaluate(self, request: AdmissionRequest) -> AdmissionResult:
        requested = request.requested_authority
        caller_available = (
            requested
            if request.caller_authority is None
            else request.caller_authority
        )
        granted = requested.intersection(caller_available)
        if self.system_authority is not None:
            granted = granted.intersection(self.system_authority)
        if request.image_authority_ceiling is not None:
            granted = granted.intersection(request.image_authority_ceiling)

        if (
            request.caller_authority is not None
            and requested.difference(caller_available).permissions
        ):
            return AdmissionResult(
                AdmissionDecision.DENY,
                Authority.empty(),
                "requested authority exceeds caller authority",
            )
        if not request.image_authority_requirements.is_subset_of(granted):
            return AdmissionResult(
                AdmissionDecision.DENY,
                Authority.empty(),
                "granted authority does not satisfy image requirements",
            )
        if granted != requested:
            return AdmissionResult(
                AdmissionDecision.DENY,
                Authority.empty(),
                "requested authority exceeds system or image authority ceiling",
            )
        return AdmissionResult(
            AdmissionDecision.ALLOW,
            granted,
            "requested authority granted",
        )
