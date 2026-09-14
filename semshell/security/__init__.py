"""Principal, authority, and admission-policy primitives."""

from semshell.security.audit import AuthorityDecisionRecord
from semshell.security.authority import Authority, Permission
from semshell.security.policy import (
    AdmissionDecision,
    AdmissionRequest,
    AdmissionResult,
    DefaultPolicy,
    Policy,
)
from semshell.security.principal import Principal

__all__ = [
    "AdmissionDecision",
    "AdmissionRequest",
    "AdmissionResult",
    "Authority",
    "AuthorityDecisionRecord",
    "DefaultPolicy",
    "Permission",
    "Policy",
    "Principal",
]
