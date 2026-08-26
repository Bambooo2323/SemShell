"""Transport-neutral external control protocol."""

from semshell.control.audit import AuditOutcome, ControlAuditRecord
from semshell.control.error import (
    ControlError,
    ControlErrorOrigin,
    SessionProtocolError,
)
from semshell.control.gateway import ControlGateway
from semshell.control.reply import ControlReply, ReplyStatus
from semshell.control.request import PROTOCOL_VERSION, ControlRequest, RequestId
from semshell.control.session import (
    ControlContext,
    ControlSession,
    RequestHandle,
    RequestState,
    SessionId,
    SessionState,
)

__all__ = [
    "PROTOCOL_VERSION",
    "AuditOutcome",
    "ControlAuditRecord",
    "ControlContext",
    "ControlError",
    "ControlErrorOrigin",
    "ControlGateway",
    "ControlReply",
    "ControlRequest",
    "ControlSession",
    "ReplyStatus",
    "RequestHandle",
    "RequestId",
    "RequestState",
    "SessionId",
    "SessionProtocolError",
    "SessionState",
]
