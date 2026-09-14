"""Deterministic JSON-compatible encoding for public Control values."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from semshell.control import ControlReply
from semshell.control.audit import AuditOutcome, ControlAuditRecord
from semshell.control.error import ControlError, ControlErrorOrigin
from semshell.control.reply import ReplyStatus
from semshell.control.request import RequestId
from semshell.control.session import SessionId
from semshell.kernel.process import (
    ErrorOrigin,
    ProcessError,
    ProcessResult,
    ProcessSnapshot,
    ProcessState,
)
from semshell.resources.types import (
    ResourceAuditEvent,
    ResourceAuditPhase,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceErrorCode,
    ResourceInvocationId,
)
from semshell.security import Permission
from semshell.security.authority import Authority
from semshell.security.principal import Principal
from semshell.software.image import CapabilitySpec, ProcessImageDescriptor

_PUBLIC_DATACLASS_TYPES = (
    Authority,
    CapabilitySpec,
    ControlAuditRecord,
    ControlError,
    ControlReply,
    Permission,
    Principal,
    ProcessError,
    ProcessImageDescriptor,
    ProcessResult,
    ProcessSnapshot,
    RequestId,
    ResourceAuditEvent,
    ResourceBindingDescriptor,
    ResourceBindingId,
    ResourceInvocationId,
    SessionId,
)

_PUBLIC_ENUM_TYPES = (
    AuditOutcome,
    ControlErrorOrigin,
    ErrorOrigin,
    ProcessState,
    ReplyStatus,
    ResourceAuditPhase,
    ResourceErrorCode,
)


class PublicValueEncodingError(TypeError):
    """A value is not part of the public JSON-compatible output domain."""


def encode_public_value(value: Any) -> Any:
    """Recursively encode supported immutable public values."""

    if isinstance(value, Enum):
        if not isinstance(value, _PUBLIC_ENUM_TYPES):
            raise PublicValueEncodingError("unsupported public enum")
        return encode_public_value(value.value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PublicValueEncodingError("non-finite number")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise PublicValueEncodingError("naive datetime")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise PublicValueEncodingError("mapping key is not a string")
        return {
            key: encode_public_value(value[key])
            for key in sorted(value)
        }
    if isinstance(value, (tuple, list)):
        return [encode_public_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = list(value)
        if all(isinstance(item, Permission) for item in items):
            items.sort(
                key=lambda item: (
                    item.capability,
                    item.scope is not None,
                    item.scope or "",
                )
            )
        else:
            items.sort(key=lambda item: canonical_json(encode_public_value(item)))
        return [encode_public_value(item) for item in items]
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value) in _PUBLIC_DATACLASS_TYPES
    ):
        return {
            field.name: encode_public_value(getattr(value, field.name))
            for field in fields(value)
        }
    raise PublicValueEncodingError("unsupported public value")


def encode_reply(reply: ControlReply) -> dict[str, Any]:
    """Encode the normative six-field reply envelope or a safe substitute."""

    try:
        encoded = {
            "request_id": str(reply.request_id),
            "operation": reply.operation,
            "status": reply.status.value,
            "value": encode_public_value(reply.value),
            "error": encode_public_value(reply.error),
            "metadata": encode_public_value(reply.metadata),
        }
    except PublicValueEncodingError:
        return {
            "request_id": str(reply.request_id),
            "operation": reply.operation,
            "status": "ENCODING_FAILED",
            "value": None,
            "error": {
                "code": "cli.encoding_failed",
                "message": "control reply value could not be encoded",
                "origin": "adapter",
                "retryable": False,
                "details": {},
            },
            "metadata": {},
        }
    return encoded


def canonical_json(value: Any) -> str:
    """Return the single canonical compact representation used by the CLI."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PublicValueEncodingError("value is not canonical JSON") from exc


def render_reply(reply: ControlReply) -> str:
    return canonical_json(encode_reply(reply))


def render_adapter_error(code: str, message: str) -> str:
    return canonical_json({"adapter_error": {"code": code, "message": message}})
