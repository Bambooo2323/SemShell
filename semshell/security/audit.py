"""Immutable audit records for process authority decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from semshell.security.authority import Authority
from semshell.security.policy import AdmissionDecision
from semshell.security.principal import Principal


@dataclass(frozen=True, slots=True)
class AuthorityDecisionRecord:
    """One explainable authority decision made before process admission."""

    occurred_at: datetime
    principal: Principal
    requester_pid: int | None
    image_reference: str
    requested_authority: Authority
    granted_authority: Authority
    decision: AdmissionDecision
    reason: str
    approval_id: str | None = None
