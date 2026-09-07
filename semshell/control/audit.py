"""Immutable in-memory audit records for the control boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from semshell.control.error import ControlError
from semshell.control.request import RequestId
from semshell.control.session import SessionId
from semshell.security.principal import Principal
from semshell.values import freeze_public_value


class AuditOutcome(StrEnum):
    """Observable outcomes recorded at the control boundary."""

    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    INTERRUPTED = "INTERRUPTED"
    LATE_SUCCEEDED = "LATE_SUCCEEDED"
    LATE_REJECTED = "LATE_REJECTED"


@dataclass(frozen=True, slots=True)
class ControlAuditRecord:
    """One immutable request reply or late-operation audit fact."""

    session_id: SessionId
    request_id: RequestId
    principal: Principal
    operation: str
    outcome: AuditOutcome
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: ControlError | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_public_value(self.details))
