"""Stable errors exposed by the transport-neutral control protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ControlErrorOrigin(StrEnum):
    """Stable layers that may reject or interrupt a control request."""

    PROTOCOL = "protocol"
    GATEWAY = "gateway"
    KERNEL = "kernel"
    POLICY = "policy"
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class ControlError:
    """Transport-neutral structured operation error."""

    code: str
    message: str
    origin: ControlErrorOrigin
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("control error code must not be empty")
        if not self.message:
            raise ValueError("control error message must not be empty")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class SessionProtocolError(RuntimeError):
    """Failure outside the admitted request/reply lifecycle."""
